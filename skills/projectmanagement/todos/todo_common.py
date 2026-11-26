"""Common core of the todo tools: mechanism shared by every front end.

Store resolution and access, record schema normalization and migration,
selector resolution, mint, search and embeddings, and the git helpers. Nothing
here parses arguments, writes to stdout or exits; failures raise ``TodoError``.
Imports no front end and no front end's local core.
"""

# pylint: disable=too-many-lines

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
)

import git_command
import todo_db
import todo_objid
import todo_search
import todo_store
import todo_embed
import todo_url

JsonDict = Dict[str, Any]


LEGACY_JSON_ENV = "TODO_USE_JSON"


# Local-first: remote polling is feature-flagged off for now. Flip to True to
# re-enable best-effort fetch on read once multi-agent sync is wanted.
FETCH_ENABLED: bool = False


# Search config keys, all per todo dir in config.json.
#   search_stopwords         the DISCOVERED stopword list (see resolve_stopwords);
#                            derived data, dropped by clear-search-data
#   search_stopword_min_idf  the IDF below which a term is a stopword here
#   embedder                 null or absent turns vector search OFF; a name/list
#                            or --embedder re-enables embedders for search
SEARCH_STOPWORDS_KEY = "search_stopwords"


SEARCH_STOPWORD_MIN_IDF_KEY = "search_stopword_min_idf"


SEARCH_EMBEDDER_KEY = "embedder"


# A term appearing in ~74% or more of the corpus (ln(N+1/df+1) < 0.3) carries
# too little signal to rank on. Tunable per store; the value only decides where
# the discovered list is cut, never whether discovery happens.
DEFAULT_STOPWORD_MIN_IDF = 0.3


class TodoError(Exception):
    """User-facing todo CLI error."""


def repo_root(start: Optional[Path] = None) -> Path:
    """Return git toplevel for *start* (default cwd)."""
    cwd: Path = start or Path.cwd()
    result = git_command.get_git().run(cwd, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise TodoError(f"not a git repository: {cwd}")
    return Path(result.stdout.strip())


def utc_now() -> str:
    """Return current UTC time as RFC3339 Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command in *root*."""
    result = git_command.get_git().run(root, *args)
    if check and result.returncode != 0:
        detail: str = (result.stderr or result.stdout or "").strip()
        raise TodoError(f"git {' '.join(args)} failed: {detail}")
    return result


def git_fetch_if_remote(root: Path) -> None:
    """Best-effort fetch when a remote exists; never fatal."""
    if not FETCH_ENABLED:
        return
    remotes = git_command.get_git().run(root, "remote", check=True)
    if not remotes.stdout.strip():
        return
    fetched = git_command.get_git().run(root, "fetch", "--quiet")
    if fetched.returncode != 0:
        print("todo.py: fetch failed; using cached refs", file=sys.stderr)


def list_branch_refs(root: Path) -> List[str]:
    """Short names for local branches and remote-tracking branches."""
    result = git_command.get_git().run(
        root,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
        "refs/remotes",
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
    result = run_git(
        root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False
    )
    return result.returncode == 0


def normalize_todo_schema(todo: JsonDict) -> JsonDict:
    """Migrate legacy field names (Chunks, Subtickets) to WorkItems, Subtodos.

    Also migrates the singular ``Parent`` dict to a ``Parent`` list of
    ``{Id, Branch}`` refs. Element 0 is the structural (fork) parent used for the
    log diff base and merge; later entries are context-only references set by
    ``set --parent`` (make-it-so).

    Also folds legacy flat ``Tags`` into plural ``Tag`` elements (v7) and renames
    legacy state keys to nouns (pre/pre-init -> groom, init -> ready, info ->
    fact; v8) so old records read back with the current shape and vocabulary even
    before a sweep.

    Delegates to ``todo_db.migrate_record_v6``/``_v7``/``_v8`` (the same
    transforms registered in ``todo_db.RECORD_MIGRATIONS`` for the migration
    sweep) so the logic lives in exactly one place. Unlike
    ``todo_db.migrate_record``, this does not stamp ``_schema`` -- ordinary
    reads/writes keep their existing shape; only an explicit ``migrate-to-latest``
    sweep version-stamps records.
    """
    todo = todo_db.migrate_record_v6(todo)
    todo = todo_db.migrate_record_v7(todo)
    return todo_db.migrate_record_v8(todo)


def migrate_store(
    store: "todo_store.TodoStore", *, dry_run: bool = False
) -> Dict[str, int]:
    """Sweep *store* to ``todo_db.SCHEMA_VERSION`` and report a summary.

    Table-level migrations apply as a side effect of the store's own storage
    calls (sqlite runs ``todo_db.migrate()`` on every connect via
    ``list_located()`` below; the file-dir backend has no table to migrate).
    This then sweeps every record via ``list_located()``, runs
    ``todo_db.migrate_record`` on a copy of each, and writes back the ones that
    changed (a changed ``_schema`` -- i.e. a record that was below latest --
    counts as changed, same as any renamed field). Unless *dry_run*, the
    changed records are ``put`` back and the store's data version is advanced
    to ``SCHEMA_VERSION``; ``dry_run`` reports the would-migrate count and
    writes nothing (no put, no data-version bump).
    """
    located = store.list_located()
    scanned = len(located)
    migrated = 0
    for repo, branch, record in located:
        original = json.loads(json.dumps(record))
        candidate = todo_db.migrate_record(json.loads(json.dumps(record)))
        if candidate != original:
            migrated += 1
            if not dry_run:
                store.put(repo, branch, candidate)
    if not dry_run:
        store.set_data_version(todo_db.SCHEMA_VERSION)
    return {"scanned": scanned, "migrated": migrated}


def use_store() -> bool:
    """Return True when tickets live in the resolved store (default).

    The store has two interchangeable backends -- sqlite.db or a
    .todo/storage json dir -- selected by the todo_storage DSN (see
    todo_store). Either way the record is a JSON object addressed by id.
    False only in legacy TODO_USE_JSON=1 mode, where the record is a
    TODO.json file committed on its branch.
    """
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
    if use_store():
        ticket = todo_store.get_store().get(repo_key(root), ref)
        if ticket is not None:
            return normalize_todo_schema(ticket)
    # *root* recorded on another machine and absent here comes back non-zero.
    show = git_command.get_git().run(root, "show", f"{ref}:TODO.json")
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
    if branch and use_store():
        ticket = todo_store.get_store().get(repo_key(root), branch)
        if ticket is not None:
            return normalize_todo_schema(ticket)
    path: Path = root / "TODO.json"
    if not path.is_file():
        return None
    if use_store():
        return None
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo_schema(parsed)


# (Summary/Body field name, its stored field_path) pairs we embed.
_EMBED_FIELDS: tuple[tuple[str, str], ...] = (
    ("Summary", "Summary.raw"),
    ("Body", "Body.raw"),
    # LongSummary is written to BE embedded (see IMPLEMENTATION.md): Body is often
    # too long to embed well, so the summary vector is the one worth matching on.
    ("LongSummary", "LongSummary.raw"),
)


def _is_flat_vector(value: Any) -> bool:
    """True for a single embedding vector: a list of >2 numbers, no bools."""
    return (
        isinstance(value, list)
        and len(value) > 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)
    )


def _is_vector(value: Any) -> bool:
    """True for a stored embedding value: a non-empty list-of-arrays, one vector per chunk.

    A legacy single-array stamp (flat list of numbers) is intentionally *not*
    matched here, so it reads as absent and is recomputed/overwritten in the new
    shape on the next write rather than lingering as a mixed-format value.
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(_is_flat_vector(v) for v in value)
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


def _tag_field_path(index: int) -> str:
    """Stored field_path for the Tag element at *index* (positional, like WorkItems.<i>)."""
    return f"Tag.{index}.raw"


def _embed_targets(todo: JsonDict) -> List[tuple[str, JsonDict, str]]:
    """Return ``(field_path, container, raw)`` for every embeddable location.

    Covers the fixed Summary/Body dicts and, positionally, every ``Tag``
    element with a non-empty raw string. ``container`` is the dict the raw text
    lives in -- embedder vectors are stamped onto it as extra keys alongside
    ``raw`` (and, for a Tag element, ``manual``). This is the single place the
    embedding machinery (cheap-embed-on-write, clear-on-write, search ranking)
    learns that Tag is plural: every other helper below iterates this list
    instead of assuming one dict per field.
    """
    targets: List[tuple[str, JsonDict, str]] = []
    for field_name, field_path in _EMBED_FIELDS:
        obj = todo.get(field_name)
        if isinstance(obj, dict):
            raw = obj.get("raw")
            if isinstance(raw, str) and raw.strip():
                targets.append((field_path, obj, raw))
    tag = todo.get("Tag")
    if isinstance(tag, list):
        for index, element in enumerate(tag):
            if isinstance(element, dict):
                raw = element.get("raw")
                if isinstance(raw, str) and raw.strip():
                    targets.append((_tag_field_path(index), element, raw))
    return targets


def _raw_map(todo: Optional[JsonDict]) -> Dict[str, str]:
    """``field_path -> raw`` for every embeddable location in *todo* (see ``_embed_targets``)."""
    if not isinstance(todo, dict):
        return {}
    return {field_path: raw for field_path, _container, raw in _embed_targets(todo)}


def _container_at(todo: JsonDict, field_path: str) -> Optional[JsonDict]:
    """Return the dict backing *field_path* in *todo* right now, or None.

    Unlike ``_embed_targets``, this does not require a non-empty raw -- it
    resolves the location itself (``Summary``/``Body``, or the ``Tag`` element
    at the path's index), so a caller can strip stale vectors even after the
    raw text has been blanked out, or find nothing when a Tag element has since
    been removed (a silent no-op, since there is nothing left to strip/stamp).
    """
    field_name = _FIELD_NAME_BY_PATH.get(field_path)
    if field_name is not None:
        obj = todo.get(field_name)
        return obj if isinstance(obj, dict) else None
    if field_path.startswith("Tag.") and field_path.endswith(".raw"):
        try:
            index = int(field_path[len("Tag.") : -len(".raw")])
        except ValueError:
            return None
        tag = todo.get("Tag")
        if (
            isinstance(tag, list)
            and 0 <= index < len(tag)
            and isinstance(tag[index], dict)
        ):
            return tag[index]
    return None


def _changed_raw_fields(old: Optional[JsonDict], new: JsonDict) -> List[str]:
    """Return the field_paths (Summary/Body/Tag.<i>) whose raw text differs.

    Tag elements are compared positionally: inserting/removing a tag shifts the
    field_path of every later element, so a removal ahead of an unrelated tag
    can flag it "changed" too (a harmless cheap re-embed; expensive vectors
    re-backfill at the next search) -- see module notes on the plural Tag
    embedding machinery.
    """
    old_map = _raw_map(old)
    new_map = _raw_map(new)
    return [
        path
        for path in sorted(set(old_map) | set(new_map))
        if old_map.get(path) != new_map.get(path)
    ]


def _strip_vectors_at(todo: JsonDict, field_path: str) -> None:
    """Drop stamped embedding vectors from the dict at *field_path*, in place."""
    obj = _container_at(todo, field_path)
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
    tag = todo.get("Tag")
    if isinstance(tag, list):
        for index, element in enumerate(tag):
            if isinstance(element, dict):
                field_path = _tag_field_path(index)
                for key, value in element.items():
                    if key not in ("raw", "manual") and _is_vector(value):
                        present.add((field_path, key))
    return present


_FIELD_NAME_BY_PATH: Dict[str, str] = dict((path, name) for name, path in _EMBED_FIELDS)


def _merge_stored_embeddings(todo: JsonDict) -> None:
    """Stamp every embeddings-table vector for this ticket into its Summary/Body/Tag dicts.

    Embedders are normally inline already: cheap vectors are written during a
    regular save and expensive vectors during search's lazy backfill. Merging the
    derived sqlite index keeps reads compatible with tickets written before lazy
    backfill also persisted the complete TODO. A store without the index
    (has_vector_index False) simply yields no rows here, so this is a no-op there.
    """
    ticket_id = str(todo.get("Id", ""))
    if not ticket_id:
        return
    store = todo_store.get_store()
    if not store.has_vector_index:
        return
    for field_path, embedder, vector in store.embeddings_for_ticket(ticket_id):
        obj = _container_at(todo, field_path)
        if isinstance(obj, dict):
            obj[embedder] = vector


def _cheap_embedding_rows(
    todo: JsonDict, existing: set
) -> List[tuple[str, str, List[List[float]]]]:
    """Stamp missing cheap vectors into the ticket JSON; return rows to store.

    ``existing`` is the set of ``(field_path, fingerprint)`` already in the db.
    Stamps ``todo`` in place so ``put_ticket`` serializes the vectors; the caller
    must ``put_embedding`` the returned rows *after* ``put_ticket`` (the FK needs
    the ticket row first). Degrades to fewer/no rows if a cheap embedder fails,
    so a broken embedder never blocks the save. Iterates ``_embed_targets``, so
    every Tag element gets the same treatment as Summary/Body.
    """
    rows: List[tuple[str, str, List[float]]] = []
    try:
        embedders = todo_embed.cheap_embedders()
    except (ValueError, RuntimeError):
        return rows
    targets = _embed_targets(todo)
    for embedder in embedders:
        try:
            fingerprint = embedder.fingerprint()
        except (ValueError, RuntimeError):
            continue
        for field_path, container, raw in targets:
            if (field_path, fingerprint) in existing:
                continue
            try:
                vec = embedder.embed(raw)
            except (ValueError, RuntimeError):
                continue
            # One vector per chunk; until chunking lands the whole field is one chunk.
            chunks = [vec]
            container[fingerprint] = chunks
            rows.append((field_path, fingerprint, chunks))
    return rows


def _drop_stale_automatic_tags(old: Optional[JsonDict], todo: JsonDict) -> None:
    """Drop AUTOMATIC Tag elements from *todo*, in place, when Summary/Body changed.

    Automatic tags (``manual: False``) are computed from a todo's Summary+Body
    text (see ``compute_auto_tags`` and doctor's recompute); once that text
    changes they no longer describe the todo, so they are dropped here to be
    recomputed fresh rather than linger stale. MANUAL elements are never
    touched. A no-op when *old* is None (a brand-new ticket has nothing to have
    changed away from -- any automatic tags seeded into its first write are
    trusted, not invalidated) or when neither Summary.raw nor Body.raw differs
    from *old*. Called from ``write_todo_worktree`` before it computes
    per-field vector changes, so ``Tag`` is already in its final shape by the
    time positional Tag.<i>.raw paths are derived from it.
    """
    if old is None:
        return
    if _raw_of(old, "Summary") == _raw_of(todo, "Summary") and _raw_of(
        old, "Body"
    ) == _raw_of(todo, "Body"):
        return
    tag = todo.get("Tag")
    if not isinstance(tag, list):
        return
    kept = [e for e in tag if not (isinstance(e, dict) and e.get("manual") is False)]
    if kept:
        todo["Tag"] = kept
    else:
        todo.pop("Tag", None)


# pylint: disable-next=too-many-locals
def write_todo_worktree(
    root: Path, todo: JsonDict, *, no_clear: bool = False, repo: Optional[str] = None
) -> None:
    """Persist ticket to the store (default) or legacy TODO.json.

    *repo* overrides the repo key the record is stored under, which otherwise
    comes from *root*. A command sweeping the WHOLE corpus (`tag-clear ALL`) must
    pass each record's own repo -- the store is shared across repos, and the
    sqlite backend keys tickets by ``(repo_path, branch)``, so writing a
    foreign-repo record under the current root would silently move it.

    On sqlite: when a raw field changed, its stored vectors are cleared (all
    embedders) so stale expensive vectors do not linger -- unless ``no_clear``,
    which keeps them (for semantically trivial edits). Cheap embedders are then
    re-populated eagerly; expensive ones are left for lazy backfill at search.
    A Summary/Body raw change also drops any AUTOMATIC Tag elements (see
    ``_drop_stale_automatic_tags``) -- also skipped under ``no_clear``, since
    that flag means the edit is being treated as semantically trivial.
    """
    normalize_todo_schema(todo)
    # Every persisted record carries objids: stamping at the single write choke
    # point means no command has to remember to do it, and a permalink minted
    # against any object stays valid because existing ids are never rewritten.
    todo_objid.stamp_objids(todo)
    todo["update_dt"] = utc_now()
    branch = str(todo.get("Branch") or current_branch(root) or "")
    if not branch:
        raise TodoError("todo missing Branch")
    if use_store():
        ticket_id = str(todo["Id"])
        store = todo_store.get_store()
        if repo is None:
            repo = repo_key(root)
        # Lock the complete read/calculate/write operation for this TODO. This
        # prevents a concurrent writer from changing raw text while its vectors
        # are being calculated, and lets us persist the fully embedded TODO once.
        with store.lock(ticket_id):
            old = store.get(repo, branch)
            if not no_clear:
                _drop_stale_automatic_tags(old, todo)
            changed = [] if no_clear else _changed_raw_fields(old, todo)
            for field_path in changed:
                _strip_vectors_at(todo, field_path)
            # Embeddings live in the todo JSON: calculate every missing cheap
            # vector before the single ticket write. The sqlite embeddings table
            # is only a derived search index, mirrored afterward when available.
            rows = _cheap_embedding_rows(todo, _json_embeddings_present(todo))
            store.put(repo, branch, todo)
            if store.has_vector_index:
                for field_path in changed:
                    store.clear_embeddings(ticket_id, field_path)
                for field_path, fingerprint, vec in rows:
                    store.put_embedding(ticket_id, field_path, fingerprint, vec)
        return
    # Legacy TODO_USE_JSON mode: the record IS the branch's TODO.json, so a
    # write is only coherent with that branch checked out.
    checked_out = current_branch(root)
    if checked_out != branch:
        raise TodoError(
            f"legacy TODO.json mode: todo {str(todo.get('Id', ''))[:8]} lives on "
            f"branch {branch!r}; checkout that branch first (currently on {checked_out!r})"
        )
    path: Path = root / "TODO.json"
    tmp: Path = root / "TODO.json.tmp"
    tmp.write_text(json.dumps(todo, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def commit_todo(root: Path, message: str) -> None:
    """Commit TODO.json in legacy file mode; no-op in store mode.

    In store mode the record lives in the store, addressed by id -- there is
    no branch-bound file to commit, and an empty marker commit would land on
    whatever branch the caller happens to have checked out.
    """
    if use_store():
        return
    if not (root / "TODO.json").is_file():
        raise TodoError("TODO.json missing; nothing to commit")
    run_git(root, "add", "TODO.json")
    run_git(root, "commit", "-m", message, check=False)


def head_sha(root: Path) -> Optional[str]:
    """Return the current HEAD commit sha, or None when there is no commit."""
    result = git_command.get_git().run(root, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def sha_matches(head: str, candidate: str) -> bool:
    """True when *candidate* names commit *head*: the exact sha, or a prefix.

    Same MIN_PREFIX convention permalinks use for the sha/subtodo_id/objid
    where-clauses (todo_url.MIN_PREFIX) -- a candidate shorter than that is
    never accepted, so a chance collision with a short abbreviation can't
    silently pass this check.
    """
    return len(candidate) >= todo_url.MIN_PREFIX and head.startswith(candidate)


def current_branch(root: Path) -> Optional[str]:
    """Return short name of the checked-out branch, if any."""
    result = git_command.get_git().run(root, "branch", "--show-current", check=True)
    name: str = result.stdout.strip()
    return name or None


def is_all_selector(selector: str) -> bool:
    """Return True when *selector* is the reserved ALL sentinel (the whole corpus).

    Uppercase, matching the --states=ALL macro convention. Ids are hex (lowercase),
    so ALL can never collide with a real ticket id prefix.
    """
    return selector == "ALL"


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


def current_state_name(todo: JsonDict) -> Optional[str]:
    """Return the single State key, if well-formed."""
    state = todo.get("State")
    if not isinstance(state, dict) or len(state) != 1:
        return None
    return next(iter(state.keys()))


def git_url_for_repo(root: Path) -> Optional[str]:
    """Best-effort origin URL for Scope.git_url."""
    result = run_git(root, "remote", "get-url", "origin", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def find_todos_by_id(root: Path, query: str) -> List[tuple[str, JsonDict]]:
    """Locate tickets whose Id matches *query* via sqlite or git refs."""
    matches: List[tuple[str, JsonDict]] = []
    seen_ids: set[str] = set()

    if use_store():
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
    loc, _ = matches[0]
    # Complain when this ticket's implementation repo is not the CWD repo.
    current = repo_key(root)
    other = loc.rsplit(":", 1)[0]
    if ":" in loc and other not in {"worktree", current} and "/" in other:
        print(
            f"todo: implementation of {query!r} is in {other}, not the current repo {current}",
            file=sys.stderr,
        )
    return matches[0]


def mint_id(root: Path, attempts: int = 1000) -> str:
    """Mint a fresh ticket Id with no 8-hex prefix clash in the repo or db."""
    for _ in range(attempts):
        ticket_id: str = hashlib.sha256(uuid.uuid1().bytes).hexdigest()
        if not find_todos_by_id(root, ticket_id[:8]):
            return ticket_id
    raise TodoError("could not mint a collision-free Id")


def import_json_ticket(
    root: Path, ticket: JsonDict, *, branch: Optional[str] = None
) -> JsonDict:
    """Load one ticket dict into the store for *root*."""
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
    ticket.setdefault("State", {"ready": {}})
    write_todo_worktree(root, ticket)
    return ticket


def import_all_json_refs(root: Path) -> int:
    """Import every TODO.json found on git refs in *root* into the store."""
    count = 0
    for ref in list_branch_refs(root):
        todo = read_todo_at_ref_legacy(root, ref)
        if todo is None:
            continue
        import_json_ticket(
            root,
            todo,
            branch=ref.split("/", 1)[-1] if ref.startswith("origin/") else ref,
        )
        count += 1
    return count


def read_todo_at_ref_legacy(root: Path, ref: str) -> Optional[JsonDict]:
    """Read TODO.json from git only (ignore sqlite)."""
    show = git_command.get_git().run(root, "show", f"{ref}:TODO.json")
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


# Search query prefix operators (no space between operator and value).
_SEARCH_TIME_OPERATORS = frozenset({"tc_before", "tc_after", "tu_before", "tu_after"})


_RFC3339_Z_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


_RFC3339_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


_RFC3339_DATE_SLASH_RE = re.compile(r"\A\d{4}/\d{2}/\d{2}\Z")


@dataclass(frozen=True)
class SearchTimeFilters:
    """Inclusive RFC3339 Z bounds on create_dt / update_dt from search terms."""

    create_before: Optional[str] = None
    create_after: Optional[str] = None
    update_before: Optional[str] = None
    update_after: Optional[str] = None

    def active(self) -> bool:
        """True when at least one bound is set."""
        return (
            self.create_before is not None
            or self.create_after is not None
            or self.update_before is not None
            or self.update_after is not None
        )


def _normalize_search_date(value: str) -> str:
    """Accept ``YYYY-MM-DD`` or ``YYYY/MM/DD``; return hyphenated date."""
    if _RFC3339_DATE_SLASH_RE.match(value):
        return value.replace("/", "-")
    return value


def _parse_search_timestamp(value: str, *, bound: str) -> str:
    """Validate *value* and return an RFC3339 Z string for comparison.

    Accepts a full timestamp (``2026-01-01T00:00:00Z``) or a date-only value
    (``2026-01-01`` or ``2026/01/01``). Date-only *after* bounds start at
    00:00:00Z that day; date-only *before* bounds end at 23:59:59Z that day.
    """
    if _RFC3339_Z_RE.match(value):
        return value
    date_value = _normalize_search_date(value)
    if _RFC3339_DATE_RE.match(date_value):
        if bound == "after":
            return f"{date_value}T00:00:00Z"
        if bound == "before":
            return f"{date_value}T23:59:59Z"
    raise TodoError(
        f"invalid search timestamp {value!r}; expected YYYY-MM-DD, YYYY/MM/DD, "
        "or YYYY-MM-DDTHH:MM:SSZ"
    )


def parse_search_query(
    terms: Sequence[str],
) -> tuple[List[str], SearchTimeFilters]:
    """Split *terms* into text matchers and colon-based time-filter operators.

    Recognized operators (glued to the value, no space): ``tc_before:``,
    ``tc_after:``, ``tu_before:``, ``tu_after:`` each followed by RFC3339 Z or a
    date-only ``YYYY-MM-DD``. Any other token is a normal search term (including strings that
    happen to contain a colon but do not match a known operator prefix).
    """
    text_terms: List[str] = []
    create_before: Optional[str] = None
    create_after: Optional[str] = None
    update_before: Optional[str] = None
    update_after: Optional[str] = None
    for term in terms:
        if ":" not in term:
            text_terms.append(term)
            continue
        prefix, _, value = term.partition(":")
        if prefix not in _SEARCH_TIME_OPERATORS:
            text_terms.append(term)
            continue
        if not value:
            raise TodoError(f"search operator {prefix!r} requires a value after ':'")
        bound = "before" if prefix.endswith("_before") else "after"
        timestamp = _parse_search_timestamp(value, bound=bound)
        if prefix == "tc_before":
            create_before = timestamp
        elif prefix == "tc_after":
            create_after = timestamp
        elif prefix == "tu_before":
            update_before = timestamp
        else:
            update_after = timestamp
    return text_terms, SearchTimeFilters(
        create_before=create_before,
        create_after=create_after,
        update_before=update_before,
        update_after=update_after,
    )


def _ticket_matches_time_filters(ticket: JsonDict, filters: SearchTimeFilters) -> bool:
    """True when *ticket* satisfies every set bound in *filters*."""
    create_dt = str(ticket.get("create_dt") or "")
    update_dt = str(ticket.get("update_dt") or "")
    if filters.create_before is not None:
        if not create_dt or create_dt > filters.create_before:
            return False
    if filters.create_after is not None:
        if not create_dt or create_dt < filters.create_after:
            return False
    if filters.update_before is not None:
        if not update_dt or update_dt > filters.update_before:
            return False
    if filters.update_after is not None:
        if not update_dt or update_dt < filters.update_after:
            return False
    return True


@dataclass(frozen=True)
class SearchTicketsResult:
    """Ranked search hits plus how many matches the state filter hid."""

    hits: List[JsonDict]
    hidden_by_status: int


def _ticket_matches_tag_filter(ticket: JsonDict, tags: Optional[frozenset]) -> bool:
    if tags is None:
        return True
    return bool(
        {
            e["raw"]
            for e in (ticket.get("Tag") or [])
            if isinstance(e, dict) and isinstance(e.get("raw"), str)
        }
        & tags
    )


def _partition_search_candidates(
    store: todo_store.TodoStore,
    *,
    states: Optional[frozenset],
    tags: Optional[frozenset],
    time_filters: SearchTimeFilters,
) -> tuple[Dict[str, JsonDict], Dict[str, JsonDict], Dict[str, tuple[str, str]]]:
    """Split store tickets into visible vs status-hidden search pools."""
    visible: Dict[str, JsonDict] = {}
    hidden: Dict[str, JsonDict] = {}
    locations: Dict[str, tuple[str, str]] = {}
    for repo_path, branch, parsed in store.list_located():
        parsed = normalize_todo_schema(parsed)
        ticket_id = str(parsed.get("Id", ""))
        if not ticket_id:
            continue
        if not _ticket_matches_tag_filter(parsed, tags):
            continue
        if not _ticket_matches_time_filters(parsed, time_filters):
            continue
        locations[ticket_id] = (repo_path, branch)
        state = current_state_name(parsed) or ""
        if states is not None and state not in states:
            hidden[ticket_id] = parsed
        else:
            visible[ticket_id] = parsed
    return visible, hidden, locations


# pylint: disable-next=too-many-arguments,too-many-locals
def _text_search_match_ids(
    tickets: Mapping[str, JsonDict],
    raws: Mapping[str, Dict[str, str]],
    text_terms: Sequence[str],
    prepared: Sequence[
        tuple[str, todo_embed.Embedder, str, List[tuple[str, List[float]]]]
    ],
    stored_by_fingerprint: Mapping[str, Mapping[tuple[str, str], List[List[float]]]],
    *,
    persist_stopwords: bool,
) -> set[str]:
    """Ticket ids that match *text_terms* under the same rankers as search."""
    if not text_terms or not tickets:
        return set()

    rankings: List[Dict[str, float]] = []
    for _name, _embedder, fingerprint, term_vecs in prepared:
        stored = stored_by_fingerprint[fingerprint]
        for _term, query_vec in term_vecs:
            scores: Dict[str, float] = {}
            for tid in tickets:
                best = 0.0
                for field_path in raws.get(tid, {}):
                    chunks = stored.get((tid, field_path)) or []
                    for chunk in chunks:
                        best = max(best, todo_embed.cosine_similarity(query_vec, chunk))
                if best > 0.0:
                    scores[tid] = best
            rankings.append(scores)

    index = todo_search.LexicalIndex(
        {tid: " ".join(raws[tid].values()) for tid in tickets}
    )
    index.use_stopwords(resolve_stopwords(index, persist=persist_stopwords))
    rankings.append(index.score(text_terms))
    fused = _rrf_fuse(rankings)
    return {tid for tid, score in fused.items() if score > 0.0}


def _rrf_fuse(rankings: List[Dict[str, float]]) -> Dict[str, float]:
    """Reciprocal rank fusion: sum 1/(k+rank) across rankers, scale-free."""
    fused: Dict[str, float] = {}
    for scores in rankings:
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (tid, _score) in enumerate(ordered, start=1):
            fused[tid] = fused.get(tid, 0.0) + 1.0 / (_RRF_K + rank)
    return fused


def resolve_embedder_names(requested: Optional[Sequence[str]]) -> List[str]:
    """Which embedders this search runs, honoring the store's ``embedder`` config.

    An explicit ``--embedder`` always wins. Otherwise the todo dir decides:

    ==========================  ==========================================
    ``config.json``             search runs with
    ==========================  ==========================================
    (key absent)                NO embedder -- lexical IDF only (default)
    ``"embedder": null``        NO embedder: lexical IDF is the only ranker
    ``"embedder": "apple"``     that embedder (comma list, like --embedder)
    ``"embedder": ["a", "b"]``  those embedders
    ==========================  ==========================================

    Vector search remains available: set ``embedder`` in config or pass
    ``--embedder`` explicitly. The default skips instantiation entirely, so
    nothing spawns the macOS NLCE sidecar and search stays fast and hermetic.
    """
    if requested:
        return list(requested)
    todo_dir = todo_db.todo_dir()
    if not todo_store.config_has(todo_dir, SEARCH_EMBEDDER_KEY):
        return []
    configured = todo_store.config_value_raw(todo_dir, SEARCH_EMBEDDER_KEY)
    if configured is None:
        return []
    if isinstance(configured, str):
        return [part.strip() for part in configured.split(",") if part.strip()]
    if isinstance(configured, list):
        return [str(part).strip() for part in configured if str(part).strip()]
    raise TodoError(
        f"config.json {SEARCH_EMBEDDER_KEY!r} must be null (no embedder), a name, "
        f"or a list of names; got {type(configured).__name__}"
    )


def resolve_stopwords(
    index: todo_search.LexicalIndex, *, persist: bool = True
) -> List[str]:
    """This corpus's stopwords: the persisted list, or discover and persist one.

    Nobody writes the list by hand. A term earns the label by falling below
    ``search_stopword_min_idf`` -- i.e. by being so widespread it carries no
    signal -- which is what makes it catch the domain words a shipped English
    list never would (``todo``, ``sha``, ``branch``, ``commit``).

    Discovery is LAZY and sticky, exactly like the embedding backfill next to
    it: computed when the config holds no list, then reused verbatim (a
    hand-edited list is therefore honored). ``clear-search-data`` is how you
    ask for a fresh one after the corpus has moved on. ``persist`` is False
    under ``--dry-run``, which still uses the discovered list but writes
    nothing.
    """
    todo_dir = todo_db.todo_dir()
    stored = todo_store.config_list(todo_dir, SEARCH_STOPWORDS_KEY)
    if stored or not index.document_count:
        return stored
    min_idf = todo_store.config_float(
        todo_dir, SEARCH_STOPWORD_MIN_IDF_KEY, DEFAULT_STOPWORD_MIN_IDF
    )
    discovered = index.stopword_candidates(min_idf)
    if discovered and persist:
        todo_store.update_config(todo_dir, {SEARCH_STOPWORDS_KEY: discovered})
    return discovered


def _solo_term_id_prefix_hit(
    terms: Sequence[str], tickets: Dict[str, JsonDict]
) -> Optional[str]:
    """Ticket id uniquely selected by *terms* as a bare hex Id prefix.

    Only engages for a single search term shaped like a selector (4+ lowercase
    hex chars) -- the same shape ``resolve_ticket_by_id`` accepts. Zero or more
    than one match is not an error here, unlike the selector resolver: it just
    means the term is not, in fact, an id prefix on this corpus, so ordinary
    ranked search decides instead.
    """
    if len(terms) != 1:
        return None
    term = terms[0]
    if len(term) < 4 or not re.fullmatch(r"[0-9a-f]+", term):
        return None
    matches = [tid for tid in tickets if id_matches(tid, term)]
    return matches[0] if len(matches) == 1 else None


# pylint: disable-next=too-many-arguments,too-many-branches,too-many-locals,too-many-statements
def search_tickets(
    terms: Sequence[str],
    *,
    limit: int = 20,
    embedder_names: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    states: Optional[frozenset] = None,
    tags: Optional[frozenset] = None,
) -> SearchTicketsResult:
    """Rank tickets by reciprocal-rank fusion over the chosen embedders + lexical.

    Reads the resolved todo directory (``$TODO_DIR``, then the ``.todo`` walk),
    the same store as ``ls``. The current directory does not need to be a git
    repo.

    ``terms`` is a list of independent search terms (google-style): each term is
    embedded and matched on its own, contributing its own ranker to the fusion,
    so their scores add. A term is the unit of embedding and matching -- a term
    holding whitespace (a quoted phrase from the shell) is embedded/matched whole
    rather than split. ``embedder_names`` defaults to the store's ``embedder``
    config -- absent or null means no embedder (see ``resolve_embedder_names``).
    A requested embedder that cannot be instantiated or run raises ``TodoError``
    (choose ``--embedder`` explicitly). Unless ``dry_run``, vectors missing for a
    chosen embedder are computed and stored (lazy backfill) before ranking; a
    ticket still missing a vector simply does not contribute to that ranker. When
    ``states`` is given, only tickets whose current State is in that set are
    considered; ``tags`` likewise keeps only tickets with a plural ``Tag``
    element (manual or automatic) whose ``raw`` is in it -- callers pass
    already-downcased tag text, matching how ``Tag.raw`` is always stored.
    Both filters apply before ranking, so the limit counts matches only.

    A solo term that uniquely prefix-matches one ticket's Id (see
    ``_solo_term_id_prefix_hit``) is pinned first regardless of its
    vector/lexical score -- a bare id prefix otherwise has no lexical or
    semantic overlap with Summary/Body text and would not reliably surface on
    its own.

    Search terms may include colon-based time operators (no space before the
    value): ``tc_before:``, ``tc_after:``, ``tu_before:``, ``tu_after:`` each
    followed by an RFC3339 Z timestamp. They are ANDed with each other and with
    text terms. Space-separated text terms are google-style OR: each term is its
    own matcher and matching more terms ranks higher; a doc matching only one
    term can still appear.
    """
    text_terms, time_filters = parse_search_query(terms)
    names = resolve_embedder_names(embedder_names)
    embedders: List[tuple[str, todo_embed.Embedder]] = []
    for name in names:
        try:
            embedders.append((name, todo_embed.get_embedder(name)))
        except (ValueError, RuntimeError) as exc:
            raise TodoError(
                f"embedder {name!r} unavailable: {exc}; "
                f"choose --embedder explicitly (e.g. --embedder mock)"
            ) from exc

    store = todo_store.get_store()
    tickets, hidden_tickets, locations = _partition_search_candidates(
        store, states=states, tags=tags, time_filters=time_filters
    )
    raws: Dict[str, Dict[str, str]] = {
        ticket_id: _raw_map(parsed) for ticket_id, parsed in tickets.items()
    }
    hidden_raws: Dict[str, Dict[str, str]] = {
        ticket_id: _raw_map(parsed) for ticket_id, parsed in hidden_tickets.items()
    }

    if not text_terms:
        ranked_ids = sorted(
            tickets.keys(),
            key=lambda tid: (
                str(tickets[tid].get("update_dt") or ""),
                str(tickets[tid].get("create_dt") or ""),
            ),
            reverse=True,
        )
        return SearchTicketsResult(
            hits=[tickets[tid] for tid in ranked_ids[:limit]],
            hidden_by_status=len(hidden_tickets),
        )

    prefix_hit = _solo_term_id_prefix_hit(text_terms, tickets)

    prepared: List[
        tuple[str, todo_embed.Embedder, str, List[tuple[str, List[float]]]]
    ] = []
    stored_by_fingerprint: Dict[str, Dict[tuple[str, str], List[List[float]]]] = {}
    for name, embedder in embedders:
        try:
            fingerprint = embedder.fingerprint()
            term_vecs = [(term, embedder.embed(term)) for term in text_terms]
        except (ValueError, RuntimeError) as exc:
            raise TodoError(f"embedder {name!r} failed: {exc}") from exc
        prepared.append((name, embedder, fingerprint, term_vecs))
        stored_by_fingerprint[fingerprint] = {
            (tid, field): vec for tid, field, vec in store.all_embeddings(fingerprint)
        }

    refreshing_embeddings = False
    if not dry_run:
        for tid, field_raws in list(raws.items()):
            needs_refresh = any(
                (tid, field_path) not in stored_by_fingerprint[fingerprint]
                for _name, _embedder, fingerprint, _term_vecs in prepared
                for field_path in field_raws
            )
            if not needs_refresh:
                continue

            repo, branch = locations[tid]
            with store.lock(tid):
                # Re-read after taking the lock. Every selected embedding for
                # this TODO is then calculated from one stable snapshot,
                # stamped into that snapshot, and persisted with one put.
                latest = store.get(repo, branch)
                if latest is None:
                    continue
                # (field_path, container, raw) for Summary/Body and every Tag
                # element -- the same target list the write path stamps.
                latest_targets = _embed_targets(latest)
                indexed = {
                    (field_path, fingerprint): chunks
                    for field_path, fingerprint, chunks in store.embeddings_for_ticket(
                        tid
                    )
                }
                new_rows: List[tuple[str, str, List[List[float]]]] = []
                for name, embedder, fingerprint, _term_vecs in prepared:
                    for field_path, container, raw in latest_targets:
                        chunks = indexed.get((field_path, fingerprint))
                        if chunks is not None:
                            container[fingerprint] = chunks
                            stored_by_fingerprint[fingerprint][
                                (tid, field_path)
                            ] = chunks
                            continue
                        if not refreshing_embeddings:
                            print(
                                "refreshing embeddings",
                                end="",
                                file=sys.stderr,
                                flush=True,
                            )
                            refreshing_embeddings = True
                        try:
                            vec = embedder.embed(raw)
                        except (ValueError, RuntimeError) as exc:
                            raise TodoError(f"embedder {name!r} failed: {exc}") from exc
                        print(".", end="", file=sys.stderr, flush=True)
                        chunks = [vec]
                        container[fingerprint] = chunks
                        indexed[(field_path, fingerprint)] = chunks
                        stored_by_fingerprint[fingerprint][(tid, field_path)] = chunks
                        new_rows.append((field_path, fingerprint, chunks))

                if not new_rows:
                    continue
                store.put(repo, branch, latest)
                for field_path, fingerprint, chunks in new_rows:
                    store.put_embedding(tid, field_path, fingerprint, chunks)
                tickets[tid] = latest
                raws[tid] = {
                    field_path: raw for field_path, _container, raw in latest_targets
                }

    rankings: List[Dict[str, float]] = []
    for _name, _embedder, fingerprint, term_vecs in prepared:
        stored = stored_by_fingerprint[fingerprint]
        for _term, query_vec in term_vecs:
            scores: Dict[str, float] = {}
            for tid in tickets:
                best = 0.0
                # Every embeddable field this ticket actually has (Summary, Body,
                # and however many Tag elements) -- not a fixed pair, since Tag is
                # plural and its count varies per ticket.
                for field_path in raws.get(tid, {}):
                    chunks = stored.get((tid, field_path)) or []
                    for chunk in chunks:
                        best = max(best, todo_embed.cosine_similarity(query_vec, chunk))
                if best > 0.0:
                    scores[tid] = best
            rankings.append(scores)

    # Lexical half: one IDF ranking over all terms (their weights add), so a
    # rare term outranks a corpus-wide one instead of every term counting the
    # same. Built fresh here -- see todo_search on why none of it is persisted.
    index = todo_search.LexicalIndex(
        {tid: " ".join(raws[tid].values()) for tid in tickets}
    )
    index.use_stopwords(resolve_stopwords(index, persist=not dry_run))
    rankings.append(index.score(text_terms))

    if refreshing_embeddings:
        print("Done", file=sys.stderr, flush=True)

    fused = _rrf_fuse(rankings)
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    ordered_ids = [tid for tid, _score in ranked]
    if prefix_hit is not None:
        # Pinned first: an id prefix has no lexical/semantic score of its own,
        # so it may otherwise be absent from `fused` entirely (see _rrf_fuse).
        ordered_ids = [prefix_hit] + [tid for tid in ordered_ids if tid != prefix_hit]
    hidden_by_status = len(
        _text_search_match_ids(
            hidden_tickets,
            hidden_raws,
            text_terms,
            prepared,
            stored_by_fingerprint,
            persist_stopwords=not dry_run,
        )
    )
    return SearchTicketsResult(
        hits=[tickets[tid] for tid in ordered_ids[:limit]],
        hidden_by_status=hidden_by_status,
    )


def commit_exists(root: Path, sha: str) -> bool:
    """True when *sha* resolves to a commit in this repo (best effort)."""
    return (
        run_git(root, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode
        == 0
    )


def discover_all_tickets(root: Path) -> Dict[str, JsonDict]:
    """Map Id -> ticket for every discoverable ticket in the store or git refs."""
    tickets: Dict[str, JsonDict] = {}
    if use_store():
        repo = repo_key(root)
        for repo_path, _branch, parsed in todo_store.get_store().list_located():
            if repo_path and repo_path != repo:
                continue
            tid = str(parsed.get("Id", ""))
            if tid:
                tickets[tid] = normalize_todo_schema(parsed)
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


def _column_value(todo: JsonDict, key: str) -> str:
    """String value for a display-column *key* on *todo*."""
    if key == "state":
        return current_state_name(todo) or ""
    if key == "ctime":
        return str(todo.get("create_dt", "") or "")
    if key == "utime":
        return str(todo.get("update_dt", "") or "")
    if key == "tags":
        tag = todo.get("Tag")
        if isinstance(tag, list):
            return ",".join(
                e["raw"]
                for e in tag
                if isinstance(e, dict) and isinstance(e.get("raw"), str)
            )
        return ""
    return ""


def todo_row(todo: JsonDict) -> JsonDict:
    """Structured, JSON-serializable summary of a todo for ls/search/web.

    The single place list-style field extraction happens; callers (CLI line
    formatting, the web viewer's templates) render from these named fields
    rather than re-reading the raw todo, so there is one source of truth.
    """
    full = str(todo.get("Id", ""))
    summary = todo.get("Summary")
    summary = (
        summary.get("raw", "") if isinstance(summary, dict) else str(summary or "")
    )
    return {
        "id": full,
        "short": full[:8],
        "summary": summary,
        "state": _column_value(todo, "state"),
        "ctime": _column_value(todo, "ctime"),
        "utime": _column_value(todo, "utime"),
        "tags": _column_value(todo, "tags"),
    }


# pylint: disable-next=too-many-arguments
def run_search(
    terms: Sequence[str],
    *,
    limit: int = 20,
    embedder_names: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    states: Optional[frozenset] = None,
    tags: Optional[frozenset] = None,
) -> tuple[List[JsonDict], int]:
    """Ranked search as structured rows (relevance-rank order preserved).

    Shared by the 'search' subcommand and the web viewer so both go through the
    same vector-search backend without duplicating it. ``terms`` is the list of
    google-style search terms (see ``search_tickets``). Returns ``(rows,
    hidden_by_status)``.
    """
    result = search_tickets(
        terms,
        limit=limit,
        embedder_names=embedder_names,
        dry_run=dry_run,
        states=states,
        tags=tags,
    )
    return [todo_row(todo) for todo in result.hits], result.hidden_by_status

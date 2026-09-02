#!/usr/bin/env python3
"""AWS-style CLI for branch-bound todo tickets (sqlite-backed; legacy JSON import)."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, List, Mapping, Optional, Sequence

import todo_db
import todo_objid
import todo_search
import todo_store
import todo_embed
import todo_url
import todo_web

JsonDict = Dict[str, Any]

LEGACY_JSON_ENV = "TODO_USE_JSON"

# Local-first: remote polling is feature-flagged off for now. Flip to True to
# re-enable best-effort fetch on read once multi-agent sync is wanted.
FETCH_ENABLED: bool = False

VALID_STATES = frozenset(
    {
        "groom",  # minted, still collecting data / grooming; not yet workable (was pre/pre-init)
        "ready",  # groomed and ready to work (was init)
        "working",
        "userneeded",
        "stopped",
        "done",
        "merged",
        "rejected",  # PR closed without merging; the handoff was refused
        "waiting",
        "fact",  # never worked; an informational anchor for vector-memory recall (was info)
        "N/a",
    }
)
STOPWORDS = frozenset({"a", "an", "the", "to", "from", "for", "and", "or", "in", "on", "of"})

# Uppercase macros usable in a --states expression (see parse_state_filter). They
# expand to state sets, so a token is unambiguously a macro (UPPERCASE) or a state
# name (lowercase). FINAL is the terminated set hidden by default.
STATE_MACROS = {
    "ALL": VALID_STATES,
    "FINAL": frozenset({"done", "merged", "rejected"}),
    "PAUSING": frozenset({"waiting", "userneeded", "stopped"}),
    "WORKING": frozenset({"working"}),
    "UNSTARTED": frozenset({"groom", "ready"}),
    "INFO": frozenset({"fact"}),
}

# Default --states expression when neither --states nor -s is given; overridable
# per todo dir via config.json "default_state_filter". Hides terminated states.
DEFAULT_STATE_FILTER = "ALL,-FINAL"

# Search config keys, all per todo dir in config.json.
#   search_stopwords         the DISCOVERED stopword list (see resolve_stopwords);
#                            derived data, dropped by clear-search-data
#   search_stopword_min_idf  the IDF below which a term is a stopword here
#   embedder                 present-and-null turns vector search OFF for this
#                            store, leaving lexical IDF as the only ranker
SEARCH_STOPWORDS_KEY = "search_stopwords"
SEARCH_STOPWORD_MIN_IDF_KEY = "search_stopword_min_idf"
SEARCH_EMBEDDER_KEY = "embedder"

# A term appearing in ~74% or more of the corpus (ln(N+1/df+1) < 0.3) carries
# too little signal to rank on. Tunable per store; the value only decides where
# the discovered list is cut, never whether discovery happens.
DEFAULT_STOPWORD_MIN_IDF = 0.3


def parse_state_filter(expr: str) -> frozenset:
    """Resolve a --states expression to the set of acceptable state names.

    Terms are individual state names (lowercase; see VALID_STATES) or UPPERCASE
    macros (see STATE_MACROS), expanded inline. Terms combine left-to-right with
    the operators ``+`` (union) and ``-`` (difference), no spaces; a comma is a
    synonym for ``+``. Examples: ``WORKING+PAUSING``, ``ALL,-done``, ``ALL,-FINAL``
    (the default). Raises TodoError on an unknown term.
    """
    # State names/macros contain no +/-/, so splitting on those is unambiguous.
    normalized = expr.replace(",", "+")
    terms = re.findall(r"([+-]?)([^+-]+)", normalized)
    result: set = set()
    for op, raw_term in terms:
        term = raw_term.strip()
        if not term:
            continue
        if term in STATE_MACROS:
            values = set(STATE_MACROS[term])
        elif term in VALID_STATES:
            values = {term}
        else:
            raise TodoError(
                f"unknown state term {term!r}; expected a state name or one of "
                f"{', '.join(sorted(STATE_MACROS))}"
            )
        if op == "-":
            result -= values
        else:  # "" (leading term) or "+"
            result |= values
    return frozenset(result)


def default_state_filter() -> str:
    """The default --states expression: config.json 'default_state_filter' or ALL,-FINAL."""
    return todo_store.config_value(
        todo_db.todo_dir(), "default_state_filter", DEFAULT_STATE_FILTER
    )


def resolve_state_filter(states_arg: Optional[str], show_all: bool) -> frozenset:
    """Effective ls/search state filter.

    Precedence: an explicit ``--states`` expression, else ``-s`` (which means
    ``ALL`` -- reveal everything), else the config.json default (``ALL,-FINAL``,
    which hides the terminated FINAL states). Always returns a concrete set.
    """
    if states_arg:
        expr = states_arg
    elif show_all:
        expr = "ALL"
    else:
        expr = default_state_filter()
    return parse_state_filter(expr)


class TodoError(Exception):
    """User-facing todo CLI error."""


class EditNotInteractive(TodoError):
    """A free-text arg was `EDIT` but no terminal is available to edit it."""


# Sentinel arg value: when a free-text option is passed exactly this, its real
# value is captured from $VISUAL/$EDITOR/vi (interactive) or is an error
# (non-interactive). See TodoSubCommand.edit_fields / resolve_edit_fields.
EDIT_SENTINEL = "EDIT"


def _stdio_is_interactive() -> bool:
    """True only when both stdin and stdout are a tty (an editor can run)."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (ValueError, AttributeError):
        return False


def edit_value_via_editor(todo_id: str, field: str) -> str:
    """Capture a value for *field* by launching an editor on a temp file.

    Opens ``$VISUAL`` (else ``$EDITOR`` else ``vi``) on a temp file whose only
    seeded content is a commented instruction line. Lines beginning with ``#``
    are stripped on read-back (git-style), so the instruction never leaks into
    the value; the remainder is returned with surrounding whitespace trimmed.
    Precondition: a tty is available (see ``_stdio_is_interactive``).
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    header = (
        f"# edit value for todo:{todo_id} {field}\n"
        "# lines starting with '#' are ignored\n"
    )
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".todoedit", prefix=f"{field}-", delete=False, encoding="utf-8"
    )
    try:
        handle.write(header)
        handle.close()
        subprocess.run([*shlex.split(editor), handle.name], check=True)
        with open(handle.name, encoding="utf-8") as fh:
            body = "\n".join(ln for ln in fh.read().splitlines() if not ln.startswith("#"))
        return body.strip()
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


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


def migrate_store(store: "todo_store.TodoStore", *, dry_run: bool = False) -> Dict[str, int]:
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

# Largest n-phrase window (unigram..trigram) used to mine tag candidates from
# corpus text (see _mine_tag_candidates). Ported from ef4ad78d's zero-shot
# tagger, where it also sized embedding chunks; chunking has not landed here,
# so this constant now serves candidate mining alone.
_MAX_NPHRASE = 3

# A phrase boundary is a sentence terminator followed by whitespace/EOL, or one
# or more newlines. The trailing-whitespace lookahead keeps decimals like "3.5"
# from splitting; newlines make headings, list items, and ascii-art lines each
# stand alone as their own phrase. Ported unchanged from ef4ad78d.
_PHRASE_SPLIT_RE = re.compile(r"[.!?]+(?=\s|$)|\n+")


def _split_phrases(text: str) -> List[str]:
    """Split raw text into phrases on sentence terminators and line breaks.

    A phrase is the unit between phrase separators (see ``_PHRASE_SPLIT_RE``).
    Whitespace-only fragments are dropped; each returned phrase is stripped.
    """
    return [p.strip() for p in _PHRASE_SPLIT_RE.split(text) if p.strip()]


def _nphrase_windows(text: str, max_n: int = _MAX_NPHRASE) -> List[str]:
    """Contiguous 1..max_n phrase windows over *text* (its n-phrases).

    Each window joins its phrases with a single space. Source order is
    preserved and duplicates are kept; callers dedup when they need a set
    (candidate mining) but not when they need one window per occurrence.
    """
    phrases = _split_phrases(text)
    windows: List[str] = []
    for n in range(1, max_n + 1):
        for i in range(len(phrases) - n + 1):
            windows.append(" ".join(phrases[i : i + n]))
    return windows


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
    return isinstance(value, list) and len(value) > 0 and all(_is_flat_vector(v) for v in value)


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
        if isinstance(tag, list) and 0 <= index < len(tag) and isinstance(tag[index], dict):
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
    if _raw_of(old, "Summary") == _raw_of(todo, "Summary") and _raw_of(old, "Body") == _raw_of(
        todo, "Body"
    ):
        return
    tag = todo.get("Tag")
    if not isinstance(tag, list):
        return
    kept = [e for e in tag if not (isinstance(e, dict) and e.get("manual") is False)]
    if kept:
        todo["Tag"] = kept
    else:
        todo.pop("Tag", None)


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


# Which State metadata each state actually keeps. A state absent here keeps none
# (groom, ready, fact, waiting, N/a). Metadata a state does not keep used to be
# accepted and silently dropped; set_state now rejects it, so a flag that would
# have done nothing says so instead of looking like it worked.
_STATE_METADATA: Dict[str, frozenset] = {
    "working": frozenset({"owner"}),
    "userneeded": frozenset({"note"}),
    "stopped": frozenset({"note"}),
    "rejected": frozenset({"note", "pr"}),
    "done": frozenset({"last_commit"}),
    "merged": frozenset({"merged_into", "last_commit", "pr", "merge_commit"}),
}


def _as_flag(name: str) -> str:
    """Render a set_state metadata parameter as its CLI flag, for error text."""
    return "--" + name.replace("_", "-")


def set_state(
    todo: JsonDict,
    state: str,
    *,
    note: Optional[str] = None,
    last_commit: Optional[str] = None,
    merged_into: Optional[str] = None,
    owner: Optional[str] = None,
    pr: Optional[int] = None,
    merge_commit: Optional[str] = None,
) -> None:
    """Replace State with a single-key object.

    ``merged`` covers BOTH handoff shapes, distinguished by which keys are set:
    a subtodo absorbed by its parent (``merged_into`` = parent branch) and a root
    todo whose branch was handed to a PR (``pr``, plus ``merge_commit`` once that
    PR actually merged). ``rejected`` is the PR-closed-unmerged outcome and keeps
    the ``pr`` it was refused under, so doctor can re-check a reopened PR.

    Raises TodoError when *state* is unknown, or when metadata is supplied that
    the target state does not keep (see ``_STATE_METADATA``) -- silently dropping
    it would make a no-op flag look like it took effect.
    """
    if state not in VALID_STATES:
        raise TodoError(f"invalid state {state!r}")
    supplied = {
        name
        for name, given in (
            ("note", note),
            ("last_commit", last_commit),
            ("merged_into", merged_into),
            ("owner", owner),
            ("pr", pr),
            ("merge_commit", merge_commit),
        )
        if given is not None
    }
    allowed = _STATE_METADATA.get(state, frozenset())
    inapplicable = sorted(supplied - allowed)
    if inapplicable:
        takes = ", ".join(_as_flag(n) for n in sorted(allowed)) or "no metadata"
        raise TodoError(
            f"state {state!r} does not take "
            f"{', '.join(_as_flag(n) for n in inapplicable)} (it takes: {takes})"
        )
    value: JsonDict = {}
    if state == "working" and owner:
        value["owner"] = owner
    if state in {"userneeded", "stopped", "rejected"} and note:
        value["note"] = note
    # `merged` accepts last_commit too: merge_subtodo passes one, and the State
    # table documents it. It used to be dropped here for merged, silently.
    if state in {"done", "merged"} and last_commit:
        value["last_commit"] = last_commit
    if state == "merged":
        if merged_into:
            value["merged_into"] = merged_into
        if merge_commit:
            value["merge_commit"] = merge_commit
    if state in {"merged", "rejected"} and pr is not None:
        value["pr"] = pr
    todo["State"] = {state: value}


# States that must not keep a linked worktree (scratch checkout only).
WORKTREE_TEARDOWN_STATES = frozenset({"done", "merged"})


def linked_worktrees_by_branch(root: Path) -> Dict[str, Path]:
    """Map branch name -> linked worktree path (never the main checkout)."""
    main = todo_db.main_checkout_root(root)
    listed = run_git(root, "worktree", "list", "--porcelain", check=False)
    if listed.returncode != 0:
        return {}
    out: Dict[str, Path] = {}
    current_path: Optional[Path] = None
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[len("worktree ") :].strip())
        elif line.startswith("branch ") and current_path is not None:
            ref = line[len("branch ") :].strip()
            name = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
            if main is None or current_path.resolve() != main.resolve():
                out[name] = current_path
            current_path = None
        elif line.startswith("detached") or line == "":
            current_path = None
    return out


def worktree_path_for_branch(root: Path, branch: str) -> Optional[Path]:
    """Return the linked worktree path for *branch*, if any."""
    if not branch:
        return None
    return linked_worktrees_by_branch(root).get(branch)


def intended_worktree_path(root: Path, branch: str) -> Path:
    """Return the conventional linked worktree path for *branch*."""
    return Path(todo_db.todo_dir()) / "worktrees" / repo_key(root) / branch


def resolve_ticket_branch(ticket: JsonDict, *, branch: Optional[str] = None) -> str:
    """Return the git branch name for *ticket* (label on record, not existence)."""
    ticket_id = str(ticket["Id"])
    return branch or str(ticket.get("Branch") or "") or kebab_branch_name(
        ticket_id, _raw_of(ticket, "Summary") or ""
    )


def promote_groom_todo(
    root: Path,
    ticket: JsonDict,
    *,
    branch: Optional[str] = None,
    stay_on_parent: bool = True,
    no_commit: bool = False,
) -> JsonDict:
    """Create the git branch for a groom ticket and move it to ``ready``."""
    ticket_id = str(ticket["Id"])
    branch_name = resolve_ticket_branch(ticket, branch=branch)
    if branch_exists(root, branch_name):
        raise TodoError(f"branch {branch_name!r} already exists")
    parent_branch = current_branch(root)
    run_git(root, "checkout", "-b", branch_name)
    base = head_sha(root)
    if base:
        ticket["BaseSha"] = base
    ticket["Branch"] = branch_name
    if isinstance(ticket.get("Scope"), dict):
        ticket["Scope"]["branch"] = branch_name
    set_state(ticket, "ready")
    write_todo_worktree(root, ticket)
    if not no_commit:
        commit_todo(root, f"chore(todo): init ticket {ticket_id[:8]}")
    if stay_on_parent and parent_branch:
        run_git(root, "checkout", parent_branch)
    return ticket


def maybe_init_todo_branch(
    root: Path,
    ticket: JsonDict,
    *,
    stay_on_parent: bool = True,
    no_commit: bool = False,
) -> tuple[JsonDict, bool]:
    """Run ``init`` promote when the ticket branch is absent; else noop.

    Returns ``(ticket, inited)`` where ``inited`` is True when a new branch was
    created.
    """
    branch_name = resolve_ticket_branch(ticket)
    if branch_name and branch_exists(root, branch_name):
        return ticket, False
    ticket = promote_groom_todo(
        root,
        ticket,
        branch=branch_name or None,
        stay_on_parent=stay_on_parent,
        no_commit=no_commit,
    )
    return ticket, True


def ensure_todo_worktree(root: Path, todo: JsonDict) -> JsonDict:
    """Create or reuse the linked worktree for *todo*'s branch.

    Returns a JSON-serializable payload with ``worktree`` and ``created``.
    Raises TodoError when the ticket has no Branch, the branch is missing in
    git (promote with ``init`` first), or ``git worktree add`` fails.
    """
    branch = str(todo.get("Branch") or "")
    if not branch:
        raise TodoError("ticket missing Branch; run todo init --id <selector> first")
    if not branch_exists(root, branch):
        ticket_id = str(todo.get("Id") or "")[:8]
        hint = f"todo init --id {ticket_id}" if ticket_id else "todo init"
        raise TodoError(f"branch {branch!r} does not exist; run {hint} first")

    intended = intended_worktree_path(root, branch)
    existing = worktree_path_for_branch(root, branch)
    if existing is not None:
        return {"worktree": str(existing), "created": False}

    if intended.is_dir() and not (intended / ".git").exists():
        raise TodoError(
            f"worktree path {intended} exists but is not a git worktree; "
            "remove or rename it, then retry"
        )

    main = todo_db.main_checkout_root(root) or root
    intended.parent.mkdir(parents=True, exist_ok=True)
    run_git(main, "worktree", "add", str(intended), branch)
    return {"worktree": str(intended), "created": True}


def assert_todo_worktree_removable(root: Path, branch: str) -> None:
    """Raise TodoError if the todo's linked worktree exists and is dirty."""
    path = worktree_path_for_branch(root, branch)
    if path is None:
        return
    status = run_git(path, "status", "--porcelain", check=False)
    if status.returncode != 0:
        raise TodoError(
            f"cannot inspect worktree for {branch!r} at {path}: "
            f"{(status.stderr or status.stdout or '').strip()}"
        )
    if status.stdout.strip():
        raise TodoError(
            f"worktree for {branch!r} is dirty ({path}); "
            "finish or stash before State done/merged (teardown is required)"
        )


def remove_todo_worktree_for_branch(root: Path, branch: str) -> Optional[str]:
    """Tear down the linked worktree for *branch* after done/merged.

    Idempotent when no linked worktree exists. Never removes the main checkout.
    Returns the removed path as a string, or None.
    """
    path = worktree_path_for_branch(root, branch)
    if path is None:
        return None
    assert_todo_worktree_removable(root, branch)
    main = todo_db.main_checkout_root(root) or root
    run_git(main, "worktree", "remove", str(path))
    run_git(main, "worktree", "prune", check=False)
    return str(path)


def teardown_worktree_for_terminal_state(
    root: Path, todo: JsonDict, *, state: Optional[str]
) -> Optional[str]:
    """If *state* is done/merged, remove the todo's linked worktree."""
    if state not in WORKTREE_TEARDOWN_STATES:
        return None
    branch = str(todo.get("Branch") or "")
    return remove_todo_worktree_for_branch(root, branch)


def apply_set_fields(
    todo: JsonDict,
    *,
    summary: Optional[str] = None,
    body: Optional[str] = None,
    ac: Optional[str] = None,
    state: Optional[str] = None,
    note: Optional[str] = None,
    last_commit: Optional[str] = None,
    merged_into: Optional[str] = None,
    owner: Optional[str] = None,
    pr: Optional[int] = None,
    merge_commit: Optional[str] = None,
    actual_summary: Optional[str] = None,
    long_summary: Optional[str] = None,
    parent_touched: bool = False,
    tags_touched: bool = False,
) -> Optional[str]:
    """Apply `set`-style edits to *todo* in memory (shared by `set` and `init`).

    Patches Summary/Body/AC/ActualSummary when given, and transitions State when
    *state* is given. Returns the new state name if State was changed, else None
    (the caller uses that to choose the commit message). Raises TodoError if no
    field at all was supplied. *parent_touched*/*tags_touched* count as a field
    change when the caller applies ``set --parent`` or ``set --tag/--untag``
    separately (parent needs root for back-links; tags are applied in place).
    """
    changed = False
    if summary is not None:
        todo.setdefault("Summary", {})["raw"] = summary
        changed = True
    if body is not None:
        todo.setdefault("Body", {})["raw"] = body
        changed = True
    if ac is not None:
        todo["AC"] = ac
        changed = True
    if actual_summary is not None:
        todo["ActualSummary"] = actual_summary
        changed = True
    if long_summary is not None:
        # Deliberately independent of Body: either may be written without the
        # other (see "LongSummary" in IMPLEMENTATION.md). Nothing here reads Body.
        todo.setdefault("LongSummary", {})["raw"] = long_summary
        changed = True
    if state is not None:
        set_state(todo, state, note=note, last_commit=last_commit,
                  merged_into=merged_into, owner=owner, pr=pr,
                  merge_commit=merge_commit)
        changed = True
    if not changed and not parent_touched and not tags_touched:
        raise TodoError(
            "pass at least one of --summary, --body, --ac, --state, "
            "--actual-summary, --long-summary, --parent, --tag, --untag"
        )
    return state


def _tag_elements(todo: JsonDict) -> List[JsonDict]:
    """Return ``todo["Tag"]`` as a list, tolerating an absent or malformed field."""
    tag = todo.get("Tag")
    return list(tag) if isinstance(tag, list) else []


def apply_tag_add(todo: JsonDict, *tags: str) -> None:
    """Add MANUAL tags to the plural ``Tag`` list, in place.

    Each tag is stripped and downcased; a tag already present (by that same
    downcased text, regardless of which element added it) is a no-op, so
    repeated ``tagadd`` calls stay idempotent. New elements are appended as
    ``{"raw": <downcased>, "manual": True}``; existing elements (including any
    automatic ones -- see ``compute_auto_tags``, batch B) are left untouched.
    """
    elements = _tag_elements(todo)
    seen = {e["raw"] for e in elements if isinstance(e, dict) and isinstance(e.get("raw"), str)}
    for tag in tags:
        if not isinstance(tag, str):
            continue
        raw = tag.strip().lower()
        if raw and raw not in seen:
            elements.append({"raw": raw, "manual": True})
            seen.add(raw)
    if elements:
        todo["Tag"] = elements


def apply_tag_remove(todo: JsonDict, *tags: str) -> None:
    """Remove MANUAL tags from the plural ``Tag`` list, in place.

    Matches case-insensitively against each element's downcased ``raw``. Only
    elements with ``manual: True`` are ever removed -- automatic tags (``manual:
    False``, set by doctor's auto-tagging) are doctor's to manage, never a
    human command's. Drops the whole ``Tag`` field once it is empty (optional
    fields are absent, not ``[]`` -- see doctor).
    """
    targets = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    elements = _tag_elements(todo)
    kept = [
        e
        for e in elements
        if not (
            isinstance(e, dict)
            and e.get("manual") is True
            and isinstance(e.get("raw"), str)
            and e["raw"] in targets
        )
    ]
    if kept:
        todo["Tag"] = kept
    else:
        todo.pop("Tag", None)


def apply_tag_clear(todo: JsonDict, *, include_manual: bool = False) -> int:
    """Drop tags from the plural ``Tag`` list, in place; return how many went.

    By default only AUTOMATIC elements (``manual: False``) are removed, mirroring
    which side of the field each command owns: ``tag-add``/``tag-rm`` own the
    manual elements, and the automatic ones are recomputed rather than curated,
    so wiping them is always safe. With *include_manual* the field is emptied
    outright -- hand-set tags included, which no other command will bring back.
    Drops the whole ``Tag`` field once it is empty (optional fields are absent,
    not ``[]`` -- see doctor).
    """
    elements = _tag_elements(todo)
    kept = (
        []
        if include_manual
        else [e for e in elements if not (isinstance(e, dict) and e.get("manual") is False)]
    )
    if kept:
        todo["Tag"] = kept
    else:
        todo.pop("Tag", None)
    return len(elements) - len(kept)


def tag_findings(todo: JsonDict) -> List[str]:
    """Hard findings for the plural ``Tag`` field's shape.

    ``Tag`` is optional; when present it must be a list whose every element is
    an object with a non-empty string ``raw`` and a bool ``manual``. Wired into
    ``doctor_findings``.
    """
    findings: List[str] = []
    tag = todo.get("Tag")
    if tag is None:
        return findings
    if not isinstance(tag, list):
        return ["Tag must be a list"]
    for index, element in enumerate(tag):
        if not isinstance(element, dict):
            findings.append(f"Tag.{index} must be an object")
            continue
        raw = element.get("raw")
        if not isinstance(raw, str) or not raw:
            findings.append(f"Tag.{index}.raw must be a non-empty string")
        if not isinstance(element.get("manual"), bool):
            findings.append(f"Tag.{index}.manual must be a bool")
    return findings


# Default top-k for compute_auto_tags, ported from ef4ad78d's zero-shot tagger.
_AUTO_TAG_K = 3


def _load_corpus(
    store: "todo_store.TodoStore", states: Optional[frozenset] = None
) -> tuple[Dict[str, JsonDict], Dict[str, Dict[str, str]]]:
    """Load every ticket and its embeddable raw fields (Summary/Body) through the store.

    Returns ``(tickets, raws)``: ``tickets`` maps Id -> the ticket dict; ``raws``
    maps Id -> {field_path -> raw text} over the non-empty Summary/Body fields.
    Ported from ef4ad78d's zero-shot tagger; used here only to mine the tag
    candidate domain (see ``_mine_tag_candidates``) -- Tag elements themselves
    are excluded from the mined text via ``_EMBED_FIELDS``, so a todo is never
    auto-tagged from its own already-applied tags. When *states* is given,
    only tickets whose current State is in that set are included.
    """
    tickets: Dict[str, JsonDict] = {}
    raws: Dict[str, Dict[str, str]] = {}
    for parsed in store.list_all():
        if not isinstance(parsed, dict):
            continue
        ticket_id = str(parsed.get("Id", ""))
        if not ticket_id:
            continue
        if states is not None and (current_state_name(parsed) or "") not in states:
            continue
        tickets[ticket_id] = parsed
        raws[ticket_id] = {
            field_path: raw
            for field_name, field_path in _EMBED_FIELDS
            if (raw := _raw_of(parsed, field_name)) is not None
        }
    return tickets, raws


def _mine_tag_candidates(raws: Dict[str, Dict[str, str]]) -> List[str]:
    """Deduped, downcased union of 1..3 n-phrases across the corpus -- the tag domain.

    Candidates are mined from every ticket's Summary/Body raw text. Ported from
    ef4ad78d's zero-shot tagger; adapted to downcase+strip each window before
    dedup/append (ef4's version kept source case) so a mined candidate is
    already a valid Tag.raw -- see ``apply_tag_add``, where a manual tag is
    downcased the same way. Order is first appearance, for stable output.
    """
    seen: set[str] = set()
    candidates: List[str] = []
    for field_raws in raws.values():
        for raw in field_raws.values():
            for window in _nphrase_windows(raw):
                candidate = window.strip().lower()
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
    return candidates


def compute_auto_tags(
    text: str,
    candidates: Sequence[str],
    embedder: "todo_embed.Embedder",
    k: int = _AUTO_TAG_K,
) -> List[JsonDict]:
    """Top-k AUTOMATIC Tag elements for *text*, scored against *candidates*.

    Embeds *text* once and every candidate with *embedder*, scores each
    candidate by ``todo_embed.cosine_similarity(text_vec, candidate_vec)``, and
    returns the k highest-scoring candidates as ``{"raw": <candidate>,
    "manual": False}`` elements -- ef4ad78d's zero-shot tagger scoring, adapted
    to emit plural Tag elements instead of a bare ``{candidate: score}`` map.
    ``raw`` is exactly the candidate string (no downcasing here); a caller that
    wants downcased tags mines downcased candidates -- see
    ``_mine_tag_candidates``. Ties break on score (descending) then candidate
    text (ascending) for a deterministic order. Returns fewer than *k* elements
    when there are fewer than *k* candidates.
    """
    text_vec = embedder.embed(text)
    scored = [
        (todo_embed.cosine_similarity(text_vec, embedder.embed(candidate)), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"raw": candidate, "manual": False} for _score, candidate in scored[:k]]


def add_state_set_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the State-transition args shared by `set` and `init`.

    These fold in the former `set-state` subcommand: `set --state <s>` (plus its
    metadata) replaces `set-state <s>`.
    """
    parser.add_argument(
        "--state",
        choices=sorted(VALID_STATES - {"waiting", "N/a"}),
        help="new workflow state (replaces the removed `set-state` subcommand)",
    )
    parser.add_argument("--note", help="note for userneeded/stopped/rejected")
    parser.add_argument("--last-commit", help="last commit message for done/merged")
    parser.add_argument("--merged-into", help="parent branch name for merged")
    parser.add_argument("--owner", help="owner for working")
    parser.add_argument(
        "--pr",
        type=int,
        help="pull-request number for merged/rejected: a root todo whose branch was "
        "handed off to a PR is `merged --pr N` (doctor reconciles its fate via gh)",
    )
    parser.add_argument(
        "--merge-commit",
        help="merge commit sha for merged, once the PR actually merged "
        "(doctor fills this in from gh)",
    )
    parser.add_argument(
        "--actual-summary",
        help="ActualSummary: how the work actually panned out; reused as the merge "
        "message when this todo is merged into its parent",
    )
    parser.add_argument(
        "--long-summary",
        dest="long_summary",
        help="LongSummary: a careful, reader-first summary of the Body, and the source "
        "for the summary embedding. Derived, but NOT tool-coupled to Body -- either may "
        "be written without the other. See 'Writing a LongSummary' in GROOMING.md before "
        "writing one",
    )


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
        "State": {"ready": {}},
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
# A WorkItem is either not-done freetext (kind "task") or one of four typed
# done kinds, each produced by the command that performs that work:
#   - "code"          local coding; carries a `sha` (invariant #1)
#   - "merge_subtodo" a merged subtodo; carries `subtodo_id` and a `sha`
#   - "start_subtodo" a fired subtodo; carries `subtodo_id`, no sha
#   - "checkpoint"    completed with NO commit produced (recon, waits,
#                     bookkeeping); carries `at_sha` -- observational (where
#                     HEAD stood), never attribution -- and a `message` saying
#                     what the no-code step did. Mirrors the State-value
#                     doctrine: each kind keeps only its own metadata, and
#                     inapplicable metadata raises instead of silently dropping.
# The cursor is the first not-done item (derived). Working proceeds by marking
# the cursor done and advancing; the index never decreases though the list may
# grow (invariant #3). A todo is done when nothing is not-done (invariant #7).

WORKITEM_TASK = "task"
WORKITEM_CODE = "code"
WORKITEM_MERGE_SUBTODO = "merge_subtodo"
WORKITEM_START_SUBTODO = "start_subtodo"
WORKITEM_CHECKPOINT = "checkpoint"
# git's null object id: an EXPLICIT no-change sentinel on a done code/merge
# item's `sha`. Two producers: `work-item-done --blocked`, for an item that
# CANNOT be done as written (the sentinel says "no commit, and none is coming"
# where a checkpoint says "no commit, step finished"); and the legacy retrofit
# for old records that misattribute a foreign commit, without converting the
# node to kind=checkpoint. Readers must never resolve it, attribute it, or
# report it as a branch commit; doctor accepts it mid-list and rejects it as
# the last item.
WORKITEM_NULL_SHA = "0" * 40
WORKITEM_DONE_KINDS = frozenset(
    {WORKITEM_CODE, WORKITEM_MERGE_SUBTODO, WORKITEM_START_SUBTODO, WORKITEM_CHECKPOINT}
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
    self_id = str(todo.get("Id", ""))[:8] or "<id>"
    index = cursor_index(todo)
    if index is None:
        return {
            "action": "finish",
            "command": f'todo.py set {self_id} --state done --actual-summary="..."',
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
        return {"action": "add-subtodo", "command": f"todo.py add-subtodo {self_id} --summary=..."}
    if primitive in (WORKITEM_MERGE_SUBTODO, "merge-subtodo"):
        return {"action": "merge-subtodo", "command": f"todo.py merge-subtodo {child}"}
    if primitive == "wait-and-merge" or (wait_for and execution.get("mode") == "barrier"):
        return {"action": "wait-and-merge", "command": f"todo.py wait-and-merge {ids}"}
    if primitive == "wait-for" or wait_for:
        return {"action": "wait-for", "command": f"todo.py wait-for {ids}"}
    return {"action": "work-item-done", "command": f"todo.py work-item-done {self_id}"}


def last_sha(todo: JsonDict) -> Optional[str]:
    """Sha of the last work item -- the last branch commit (invariant #6), if any.

    The no-change sentinel (WORKITEM_NULL_SHA) is not a branch commit and
    reports as None; doctor separately flags it as the last item of a done todo."""
    items = todo.get("WorkItems") or []
    if not items or not isinstance(items[-1], dict):
        return None
    sha = items[-1].get("sha")
    if sha == WORKITEM_NULL_SHA:
        return None
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


def checkpoint_workitem(at_sha: str, summary: str = "", message: str = "") -> JsonDict:
    """Build a done 'checkpoint' work item: completed with NO commit produced.

    `at_sha` is observational -- where branch HEAD stood at completion -- NOT
    attribution: a checkpoint claims no authorship of that commit (contrast
    `code_workitem`, whose `sha` means "this commit IS this item's work").
    `message` should say what the no-code step actually did; the default marks
    an explicit no-op so the trail never inherits a foreign commit's message."""
    return {
        "kind": WORKITEM_CHECKPOINT,
        "summary": summary,
        "at_sha": at_sha,
        "message": message or "(no-op checkpoint; no commit produced)",
        "done": True,
    }


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


def mint_id(root: Path, attempts: int = 1000) -> str:
    """Mint a fresh ticket Id with no 8-hex prefix clash in the repo or db."""
    for _ in range(attempts):
        ticket_id: str = hashlib.sha256(uuid.uuid1().bytes).hexdigest()
        if not find_todos_by_id(root, ticket_id[:8]):
            return ticket_id
    raise TodoError("could not mint a collision-free Id")


def import_json_ticket(root: Path, ticket: JsonDict, *, branch: Optional[str] = None) -> JsonDict:
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

# Search query prefix operators (no space between operator and value).
_SEARCH_TIME_OPERATORS = frozenset(
    {"tc_before", "tc_after", "tu_before", "tu_after"}
)
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


def _ticket_matches_time_filters(
    ticket: JsonDict, filters: SearchTimeFilters
) -> bool:
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


def _text_search_match_ids(
    tickets: Mapping[str, JsonDict],
    raws: Mapping[str, Dict[str, str]],
    text_terms: Sequence[str],
    prepared: Sequence[tuple[str, todo_embed.Embedder, str, List[tuple[str, List[float]]]]],
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
    (key absent)                every non-hidden embedder -- the default
    ``"embedder": null``        NO embedder: lexical IDF is the only ranker
    ``"embedder": "apple"``     that embedder (comma list, like --embedder)
    ``"embedder": ["a", "b"]``  those embedders
    ==========================  ==========================================

    The null case is the point: it skips instantiation entirely, so nothing
    spawns the macOS NLCE sidecar, nothing backfills a vector, and search stays
    fast and hermetic on a machine that cannot embed at all. It is a store-level
    policy rather than a flag because "this checkout does not do vectors" is a
    property of the checkout.
    """
    if requested:
        return list(requested)
    todo_dir = todo_db.todo_dir()
    if not todo_store.config_has(todo_dir, SEARCH_EMBEDDER_KEY):
        return todo_embed.default_embedder_names()
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


def _solo_term_id_prefix_hit(terms: Sequence[str], tickets: Dict[str, JsonDict]) -> Optional[str]:
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


def search_tickets(
    root: Path,
    terms: Sequence[str],
    *,
    limit: int = 20,
    embedder_names: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    states: Optional[frozenset] = None,
    tags: Optional[frozenset] = None,
) -> SearchTicketsResult:
    """Rank tickets by reciprocal-rank fusion over the chosen embedders + lexical.

    ``terms`` is a list of independent search terms (google-style): each term is
    embedded and matched on its own, contributing its own ranker to the fusion,
    so their scores add. A term is the unit of embedding and matching -- a term
    holding whitespace (a quoted phrase from the shell) is embedded/matched whole
    rather than split. ``embedder_names`` defaults to every non-hidden embedder.
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

    prepared: List[tuple[str, todo_embed.Embedder, str, List[tuple[str, List[float]]]]] = []
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
                    for field_path, fingerprint, chunks in store.embeddings_for_ticket(tid)
                }
                new_rows: List[tuple[str, str, List[List[float]]]] = []
                for name, embedder, fingerprint, _term_vecs in prepared:
                    for field_path, container, raw in latest_targets:
                        chunks = indexed.get((field_path, fingerprint))
                        if chunks is not None:
                            container[fingerprint] = chunks
                            stored_by_fingerprint[fingerprint][(tid, field_path)] = chunks
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
                raws[tid] = {field_path: raw for field_path, _container, raw in latest_targets}

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
    _loc, target = resolve_ticket_by_id(root, selector)
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


def format_jsonpath(keys: Sequence[Any]) -> str:
    """Render path segments as a dotted path, or ``<root>`` when empty."""
    if not keys:
        return "<root>"
    return ".".join(str(key) for key in keys)


def available_path_options(node: Any) -> str:
    """Comma-separated keys (dicts) or indices (lists) at *node*; empty otherwise."""
    if isinstance(node, dict):
        return ",".join(sorted(str(key) for key in node.keys()))
    if isinstance(node, list):
        return ",".join(str(index) for index in range(len(node)))
    return ""


def no_such_path_error(worked: Sequence[Any], missing: Any, current: Any) -> TodoError:
    """Build a TodoError naming the path that worked, the missing field, and options."""
    return TodoError(
        f"path {format_jsonpath(worked)} no such field {missing}. "
        f"available: {available_path_options(current)}"
    )


def resolve_path_segment(current: Any, key: Any, worked: Sequence[Any]) -> Any:
    """Descend one path segment; raise TodoError with context on failure."""
    if isinstance(key, int):
        if not isinstance(current, list):
            raise TodoError(
                f"path {format_jsonpath(worked)} expected list at segment {key!r}; "
                f"available: {available_path_options(current)}"
            )
        if key < 0 or key >= len(current):
            raise no_such_path_error(worked, key, current)
        return current[key]
    if not isinstance(current, dict):
        raise TodoError(
            f"path {format_jsonpath(worked)} expected object at segment {key!r}; "
            f"available: {available_path_options(current)}"
        )
    if key not in current:
        raise no_such_path_error(worked, key, current)
    return current[key]


def get_at_path(root: JsonDict, path_str: str) -> Any:
    """Return the value at *path_str* within *root*."""
    current: Any = root
    worked: List[Any] = []
    for key in parse_jsonpath(path_str):
        current = resolve_path_segment(current, key, worked)
        worked.append(key)
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
    worked: List[Any] = []
    for index, key in enumerate(keys[:-1]):
        next_key = keys[index + 1]
        if isinstance(key, int):
            current = resolve_path_segment(current, key, worked)
        else:
            if not isinstance(current, dict):
                raise TodoError(
                    f"path {format_jsonpath(worked)} expected object at segment {key!r}; "
                    f"available: {available_path_options(current)}"
                )
            nested = current.get(key)
            if not isinstance(nested, (dict, list)):
                current[key] = [] if isinstance(next_key, int) else {}
                nested = current[key]
            current = nested
        worked.append(key)
    last = keys[-1]
    if isinstance(last, int):
        if not isinstance(current, list):
            raise TodoError(
                f"path {format_jsonpath(worked)} expected list at final segment {last!r}; "
                f"available: {available_path_options(current)}"
            )
        if last < 0 or last >= len(current):
            raise no_such_path_error(worked, last, current)
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise TodoError(
                f"path {format_jsonpath(worked)} expected object at final segment {last!r}; "
                f"available: {available_path_options(current)}"
            )
        current[last] = value


# Subtodos[].State for a child-declared informational back-link: a follow-only
# link (HATEOAS) inserted by `set --parent` and repaired by `doctor`, distinct
# from a tracked subtodo the parent must merge. Excluded from merge-completeness.
SUBTODO_STATE_INFO = "INFO"


def subtodo_entry_from_child(child: JsonDict) -> JsonDict:
    """Build a parent Subtodos row from a child todo."""
    return {
        "Id": child["Id"],
        "Branch": child.get("Branch", ""),
        "Summary": child.get("Summary", {}).get("raw", ""),
        "State": current_state_name(child) or "ready",
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


def remove_info_backlink(parent: JsonDict, child_id: str) -> bool:
    """Drop an INFO Subtodos entry for *child_id* from *parent*.

    Returns True when the parent changed. Leaves non-INFO (tracked/mergeable)
    Subtodos entries alone -- those belong to add-subtodo, not set --parent.
    """
    subtodos: List[JsonDict] = list(parent.get("Subtodos") or [])
    kept: List[JsonDict] = []
    changed = False
    for entry in subtodos:
        if (
            isinstance(entry, dict)
            and entry.get("Id") == child_id
            and entry.get("State") == SUBTODO_STATE_INFO
        ):
            changed = True
            continue
        kept.append(entry)
    if changed:
        parent["Subtodos"] = kept
    return changed


def resolve_parent_refs(root: Path, parent_ids: Sequence[str]) -> List[JsonDict]:
    """Resolve ``set --parent`` selectors to ordered ``{Id, Branch}`` refs.

    Blank tokens are skipped (so ``--parent=`` alone yields an empty desired
    list and clears Parent). Duplicate Ids keep the first occurrence.
    """
    refs: List[JsonDict] = []
    seen: set = set()
    for raw in parent_ids:
        parent_id = raw.strip()
        if not parent_id:
            continue
        _loc, ptodo = resolve_ticket_by_id(root, parent_id)
        full_id = str(ptodo["Id"])
        if full_id in seen:
            continue
        seen.add(full_id)
        refs.append({"Id": full_id, "Branch": str(ptodo.get("Branch", ""))})
    return refs


def apply_parent_links(
    root: Path,
    child: JsonDict,
    parent_ids: Sequence[str],
    *,
    dry_run: bool = False,
) -> List[str]:
    """Make-it-so: set *child*.Parent to *parent_ids* and sync INFO back-links.

    Desired end-state replaces the child's Parent list. Former parents that
    carried a follow-only INFO back-link to this child lose it; desired parents
    gain (or refresh) one. Tracked/mergeable Subtodos rows are never removed.
    Returns human descriptions of back-link changes. Child Parent is updated in
    memory always; parent writes are skipped when *dry_run* or not sqlite.
    """
    child_id = str(child.get("Id") or "")
    desired = resolve_parent_refs(root, parent_ids)
    for ref in desired:
        if ref["Id"] == child_id:
            raise TodoError("a todo cannot be its own parent")

    old_ids: set = set()
    for ref in child.get("Parent") or []:
        if isinstance(ref, dict):
            oid = str(ref.get("Id") or "")
            if oid:
                old_ids.add(oid)
    new_ids = {str(ref["Id"]) for ref in desired}
    child["Parent"] = desired

    changes: List[str] = []
    if not use_store():
        return changes

    current = repo_key(root)
    for old_id in sorted(old_ids - new_ids):
        try:
            loc, parent = resolve_ticket_by_id(root, old_id)
        except TodoError:
            continue
        parent_repo = loc.rsplit(":", 1)[0] if ":" in loc else ""
        if parent_repo and parent_repo not in ("worktree", current):
            continue
        if remove_info_backlink(parent, child_id):
            changes.append(f"parent {old_id[:8]} -/ INFO back-link {child_id[:8]}")
            if not dry_run:
                write_todo_worktree(root, parent)

    changes.extend(reestablish_backlinks(root, child, dry_run=dry_run))
    return changes


def reestablish_backlinks(root: Path, child: JsonDict, *, dry_run: bool = False) -> List[str]:
    """Make each of *child*'s `Parent` refs point back at the child.

    For every parent the child references, ensure the parent's Subtodos carries
    an INFO back-link to this child (so a reader can follow parent -> child, not
    just child -> parent). Returns human descriptions of the back-links added or
    refreshed; writes them unless *dry_run*.

    Best-effort and store-only: unresolvable and cross-repo parents are skipped
    (a write keys by the current repo, so persisting another repo's parent would
    misfile it), and legacy JSON mode -- where a write targets the current
    branch's file -- makes no changes.
    """
    if not use_store():
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


def child_is_tracked_subtodo(root: Path, child: JsonDict) -> bool:
    """Whether *child* is a genuinely TRACKED subtodo of any of its Parent refs.

    A child's own `Parent` refs look identical whether the link is a real,
    mergeable subtodo (created via `add-subtodo`) or a purely informational
    back-link (created via `set --parent` / `reestablish_backlinks`); the
    distinction lives only on the *parent's* own Subtodos[].State for this
    child's entry -- SUBTODO_STATE_INFO means follow-only, anything else means
    the parent must still merge this child (see `unmerged_subtodos`, the
    parent-side version of this same rule).

    Best-effort and skip-on-failure, mirroring `reestablish_backlinks`:
    unresolvable and cross-repo parents are simply skipped rather than raising.
    Returns False when no parent resolves to a non-INFO entry for this child,
    including when Parent is empty or every parent ref fails to resolve.
    """
    child_id = str(child.get("Id") or "")
    current = repo_key(root)
    for ref in child.get("Parent") or []:
        if not isinstance(ref, dict):
            continue
        parent_id = str(ref.get("Id") or "")
        if not parent_id:
            continue
        try:
            loc, parent = resolve_ticket_by_id(root, parent_id)
        except TodoError:
            continue
        parent_repo = loc.rsplit(":", 1)[0] if ":" in loc else ""
        if parent_repo and parent_repo not in ("worktree", current):
            continue  # cross-repo parent: not authoritative here
        for entry in parent.get("Subtodos") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Id") or "") != child_id:
                continue
            if entry.get("State") != SUBTODO_STATE_INFO:
                return True
    return False


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
    """Set *jsonpath* to an already-parsed *value* on a selected ticket.

    The selector resolves the todo by Id through the store and writes it back
    store-only (sqlite or json-dir backend): no branch checkout and no commit.
    Storage access -- which reading the todo already proves we have -- is all
    that is required, so this works on a branchless ``groom`` todo (it carries
    a Branch *label* but has no git branch yet) and never lands a commit on
    whatever branch the caller happens to be on. ``stay`` is retained for CLI
    backward compatibility but is a no-op: with no checkout there is no branch
    to return from. ``no_commit`` only matters in legacy TODO_USE_JSON mode,
    where the record is a branch-bound file (see ``commit_todo``).
    """
    _, todo = resolve_ticket_by_id(root, selector)
    set_at_path(todo, jsonpath, value)
    write_todo_worktree(root, todo, no_clear=no_clear)
    if not no_commit:
        commit_todo(root, f"chore(todo): update {jsonpath}")
    return get_at_path(todo, jsonpath)


def merge_subtodo(
    root: Path,
    child_selector: str,
    *,
    merged_into: Optional[str] = None,
    last_commit: Optional[str] = None,
) -> JsonDict:
    """Mark a child todo merged and update its parent's bookkeeping.

    The parent is the child's ``Parent[0]`` ref -- the structural parent
    ``add-subtodo`` recorded. Both records are updated through the store with
    no branch checkout. The recorded merge sha is the tip of the parent's
    branch: the caller's actual git merge (or absorption) commit, which the
    caller must have landed before calling (invariant #6 keeps holding, with a
    real sha instead of a marker commit).
    """
    _, child = resolve_ticket_by_id(root, child_selector)
    child_id = str(child["Id"])
    child_branch = str(child.get("Branch") or "")
    if not child_branch:
        raise TodoError("child ticket missing Branch")
    child_state = current_state_name(child)
    if child_state not in {"done", "merged"}:
        raise TodoError(
            f"child {child_id[:8]} is {child_state!r}; expected done before merge-subtodo"
        )
    parents = child.get("Parent") or []
    first_ref = parents[0] if parents and isinstance(parents[0], dict) else {}
    parent_id_ref = str(first_ref.get("Id") or "")
    if not parent_id_ref:
        raise TodoError(
            f"child {child_id[:8]} has no Parent ref; cannot locate the parent todo"
        )
    _, parent = resolve_ticket_by_id(root, parent_id_ref)
    parent_branch = str(parent.get("Branch") or "")
    if not parent_branch:
        raise TodoError(f"parent {parent_id_ref[:8]} ticket missing Branch")

    merge_target = merged_into or parent_branch
    merge_sha = run_git(
        root, "rev-parse", "--verify", "--quiet", parent_branch, check=False
    ).stdout.strip()
    if not merge_sha:
        raise TodoError(
            f"parent branch {parent_branch!r} not found here; git-merge the child "
            "into the parent branch before merge-subtodo"
        )

    set_state(child, "merged", merged_into=merge_target, last_commit=last_commit)
    write_todo_worktree(root, child)

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

    update_subtodo_state(parent, child_id, "merged")
    index = mark_cursor_done(parent, merge_subtodo_workitem(child_id, merge_sha, summary=""))
    if not parent["WorkItems"][index].get("summary"):
        parent["WorkItems"][index]["summary"] = merge_subject
    write_todo_worktree(root, parent)
    # State merged implies no linked worktree for the child (property of terminal).
    remove_todo_worktree_for_branch(root, child_branch)
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
            _, todo = resolve_ticket_by_id(root, selector)
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
        "LongSummary",
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
        "Tag",
        "Tags",
        "WorkItems",
        "create_dt",
        "update_dt",
        "_schema",  # stamped by todo_db.migrate_record on a migrate-to-latest sweep
        "_nextobjid",  # objid allocation cursor; see todo_objid
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
        if k == WORKITEM_CHECKPOINT:
            if not (isinstance(item.get("at_sha"), str) and item.get("at_sha")):
                findings.append(f"WorkItems.{index} checkpoint item is missing at_sha")
            if item.get("sha"):
                findings.append(
                    f"WorkItems.{index} checkpoint item carries a sha; a checkpoint claims "
                    "no commit (observational position goes in at_sha)"
                )
    # a done todo must not end in start_subtodo, checkpoint, or a no-change
    # sentinel -- it must be a real code/merge commit so last-sha is the
    # branch's last commit (#6)
    if items and is_done(todo):
        last = items[-1]
        if isinstance(last, dict) and workitem_kind(last) in (
            WORKITEM_START_SUBTODO,
            WORKITEM_CHECKPOINT,
        ):
            findings.append(
                f"last work item is {workitem_kind(last)}; a done todo must end in a "
                "code or merge commit (#6)"
            )
        elif isinstance(last, dict) and last.get("sha") == WORKITEM_NULL_SHA:
            findings.append(
                "last work item carries the no-change sentinel sha; a done todo must "
                "end in a code or merge commit (#6)"
            )
    return findings


# A parent in any of these has terminated, so an unmerged tracked subtodo can no
# longer be merged and escalates from warning to hard finding. `rejected` counts:
# it is a FINAL disposition, and a spawn without a merge must not survive it.
TERMINAL_PARENT_STATES = ("done", "merged", "rejected")


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


def objid_findings(todo: JsonDict) -> List[str]:
    """Return hard findings about objids: the permalink handles must hold.

    A permalink names an object by objid, so a missing, malformed, or reused id
    is a broken link, not cosmetic drift. ``_nextobjid`` must also stay ahead of
    every id in the record, or the next allocation would hand out one that is
    already in use and silently move an existing permalink onto a new object.

    None of this should ever fire in normal operation -- the write choke point
    stamps every record and doctor's own schema sweep backfills legacy ones --
    so a finding here means something wrote the store outside todo.py.
    """
    findings: List[str] = []
    highest = -1
    by_objid: Dict[str, str] = {}
    for path, obj in todo_objid.iter_objects(todo):
        value = obj.get(todo_objid.OBJID_KEY)
        if value is None:
            findings.append(f"{path} has no objid")
            continue
        if not todo_objid.is_objid(value):
            findings.append(f"{path}.objid {value!r} is not 4+ lowercase hex")
            continue
        if value in by_objid:
            findings.append(f"{path}.objid {value} duplicates {by_objid[value]}")
            continue
        by_objid[value] = path
        highest = max(highest, int(value, 16))
    if highest < 0:
        return findings
    cursor = todo.get(todo_objid.NEXT_OBJID_KEY)
    if not isinstance(cursor, int) or isinstance(cursor, bool):
        findings.append(f"{todo_objid.NEXT_OBJID_KEY} must be an integer")
    elif cursor <= highest:
        findings.append(
            f"{todo_objid.NEXT_OBJID_KEY} {cursor} is not past the highest "
            f"objid {todo_objid.format_objid(highest)}"
        )
    return findings


def doctor_findings(root: Path, selector: str) -> List[str]:
    """Return hard doctor findings for the selected todo (shape invariants)."""
    _, todo = resolve_ticket_by_id(root, selector)
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
    # SHAPE ONLY. doctor deliberately does not check that LongSummary still
    # describes Body: the two are independent by design (either may be written
    # without the other -- see "LongSummary" in IMPLEMENTATION.md), so a LongSummary
    # that disagrees with its Body is not a defect the tool can judge.
    long_summary = todo.get("LongSummary")
    if long_summary is not None and (
        not isinstance(long_summary, dict) or not isinstance(long_summary.get("raw"), str)
    ):
        findings.append("LongSummary.raw must be a string")
    tags = todo.get("Tags")
    if tags is not None and (
        not isinstance(tags, list)
        or not all(isinstance(tag, str) and tag for tag in tags)
    ):
        findings.append("Tags must be a list of non-empty strings")
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
    findings.extend(tag_findings(todo))
    findings.extend(objid_findings(todo))
    findings.extend(wait_graph_findings(root, todo))
    # done/merged must not retain a linked worktree (tool-enforced property).
    if parent_state in WORKTREE_TEARDOWN_STATES:
        branch = str(todo.get("Branch") or "")
        leftover = worktree_path_for_branch(root, branch) if branch else None
        if leftover is not None:
            findings.append(
                f"State {parent_state!r} still has linked worktree at {leftover} "
                "(teardown is required for done/merged)"
            )
    return findings


def doctor_warnings(root: Path, selector: str) -> List[str]:
    """Return soft doctor warnings that need an absent subbranch or other repo to
    verify. These never fail doctor, so transitional and cross-repo todos (where
    not every subbranch is available) do not hard-fail."""
    _, todo = resolve_ticket_by_id(root, selector)
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
                    resolve_ticket_by_id(root, child_id[:8])
                except TodoError:
                    warnings.append(f"Subtodos.{index}.Id {child_id[:8]} not discoverable here")
    items = todo.get("WorkItems") or []
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            sha = item.get("sha")
            if (
                isinstance(sha, str)
                and sha
                and sha != WORKITEM_NULL_SHA  # explicit no-change sentinel, never resolvable
                and not commit_exists(root, sha)
            ):
                warnings.append(f"WorkItems.{index}.sha {sha[:8]} not found in this repo")
            sub = item.get("subtodo_id")
            if isinstance(sub, str) and sub:
                try:
                    resolve_ticket_by_id(root, sub[:8])
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
                resolve_ticket_by_id(root, child_selector)
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
            _, child = resolve_ticket_by_id(root, selector)
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
    # Free-text arg dests eligible for the `EDIT` sentinel (see EDIT_SENTINEL).
    edit_fields: ClassVar[Sequence[str]] = ()

    def __init__(self, args: argparse.Namespace) -> None:
        """Copy parsed argparse fields onto the command object."""
        self.args = args
        for name, value in vars(args).items():
            if name != "command_cls":
                setattr(self, name, value)

    def __getattr__(self, name: str) -> Any:
        """Expose argparse fields as dynamic command attributes."""
        return getattr(self.args, name)

    def resolve_edit_fields(self, todo_id: str) -> None:
        """Expand any `EDIT`-valued free-text arg (see ``edit_fields``) in place.

        For each eligible arg whose value is exactly ``EDIT``: in an interactive
        terminal, capture the value via ``$VISUAL``/``$EDITOR``/vi; otherwise
        raise ``EditNotInteractive`` (which exits 1). Multiple such args are
        resolved in ``edit_fields`` order. Callers that create a todo MUST call
        this before creating anything, so a non-interactive `EDIT` leaves no
        todo behind.
        """
        for field in self.edit_fields:
            if getattr(self, field, None) != EDIT_SENTINEL:
                continue
            if not _stdio_is_interactive():
                raise EditNotInteractive(
                    f"--{field.replace('_', '-')}=EDIT requires an interactive terminal"
                )
            value = edit_value_via_editor(todo_id, field)
            setattr(self.args, field, value)
            self.__dict__[field] = value

    @classmethod
    def register(cls, subparsers: argparse._SubParsersAction) -> None:
        """Attach this command class to the main argparse subparser collection."""
        for name in cls.command_names:
            parser: argparse.ArgumentParser = subparsers.add_parser(
                name,
                # No `help=`: argparse only adds a command to its own flat
                # listing when that kwarg is present (it builds a
                # _ChoicesPseudoAction to hold it), and argparse.SUPPRESS is
                # NOT honored here -- it renders the sentinel verbatim. The
                # grouped listing in the epilog carries doc_short instead.
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


# --- command groups --------------------------------------------------------
#
# The taxonomy of the CLI, and nothing else. A group adds no behavior, declares
# no command_names, and stays abstract; it exists so that related commands are
# visibly related in the source, so --help can list them under a heading, and so
# registration can WALK the tree instead of consulting a hand-kept list that the
# next new command would forget to join.
#
# Groups nest, and the inner ones are deliberately cosmetic: they subdivide a
# long group in the source without inventing a heading nobody asked for, because
# a leaf is listed under its nearest TITLED ancestor. So work-item-add sits in
# WorkItemEditCommand for the reader and under "Work item" for the user.
#
# Adding a command means picking its group -- there is nowhere else to put it,
# and _command_leaves refuses to find it anywhere else (see the orphan test).


class CommandGroup(TodoSubCommand):
    """An organizational node of the command tree; never runnable itself.

    Abstract by omission: a group implements neither configure_parser nor do,
    so ABC refuses to instantiate one even if a caller tried.
    """

    group_title: ClassVar[str] = ""


class ManagementCommand(CommandGroup):
    """Acts on the store, the corpus, or the environment -- not on one todo."""

    group_title: ClassVar[str] = "Management"


class StoreMaintenanceCommand(ManagementCommand):
    """Audits, migrates, or moves the store as a whole."""


class CorpusQueryCommand(ManagementCommand):
    """Finds or renders todos across the corpus."""


class EnvironmentCommand(ManagementCommand):
    """Reports where things live, or serves them."""


class TodoCrudCommand(CommandGroup):
    """Creates, reads, or edits one todo record."""

    group_title: ClassVar[str] = "Todo CRUD"


class TodoCreateCommand(TodoCrudCommand):
    """Brings a todo into being: the two-phase mint -> init."""


class TodoFieldCommand(TodoCrudCommand):
    """Reads or writes fields of an existing record."""


class TagCommand(TodoCrudCommand):
    """Edits the plural Tag field."""


class WorkItemCommand(CommandGroup):
    """Acts on a todo's WorkItems -- the ordered plan and its cursor."""

    group_title: ClassVar[str] = "Work item"


class WorkItemEditCommand(WorkItemCommand):
    """Edits the not-done frontier of the plan; never the done prefix."""


class WorkItemProgressCommand(WorkItemCommand):
    """Advances the cursor, or reports where it stands."""


class SubtodoCommand(CommandGroup):
    """Parent/child bookkeeping and the checkouts children are worked in."""

    group_title: ClassVar[str] = "Subtodo and coordination"


class SubtodoMergeCommand(SubtodoCommand):
    """Forks a child, or lands one back on its parent."""


class SubtodoWaitCommand(SubtodoCommand):
    """Blocks on children reaching a state."""


# Group order is help order; leaf order within a group is source order.
COMMAND_GROUPS: Sequence[type[CommandGroup]] = (
    ManagementCommand,
    TodoCrudCommand,
    WorkItemCommand,
    SubtodoCommand,
)


def _command_leaves(node: type[TodoSubCommand]) -> Iterator[type[TodoSubCommand]]:
    """Every runnable command at or under *node*, in source order.

    A leaf is a class that declares command_names; everything else is taxonomy.
    """
    for sub in node.__subclasses__():
        if sub.command_names:
            yield sub
        yield from _command_leaves(sub)


class MintCommand(TodoCreateCommand):
    command_names = ("mint",)
    doc_short: ClassVar[str] = "Mint todo Id"
    doc_long: ClassVar[str] = (
        "Mint creates a new TODO and prints its Id. It hashes a uuid1 value into the canonical "
        "64-character lowercase hex Id (collision-checked against existing todos), then materializes "
        "a data-collection record for it: State `groom` (still collecting data / grooming), no git "
        "branch, store-only (no commit). Fill it in with `set <id>`; run `init` when it is "
        "ready to be worked (gives it a branch and moves it to `ready`). Prints only the Id so "
        "callers can capture it directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register mint arguments."""

    def do(self) -> int:
        """Create a groom (data-collection) todo and print its Id.

        The record is store-only: no git branch and no commit at groom. The
        Branch is a placeholder (Id[0:8]) until `set` finalizes it from the
        summary and `init` creates the actual branch.
        """
        root = self.root()
        ticket_id = mint_id(root)
        branch = ticket_id[:8]  # placeholder key; `set` finalizes it from summary
        ticket = build_ticket_skeleton(root, ticket_id, branch, "", "", "")
        set_state(ticket, "groom")
        write_todo_worktree(root, ticket)
        print(ticket_id)
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
    """Recursively shorten embedding-like numeric lists to their first two elements.

    An embedding is a list of more than two numbers (never bools). JSON has no
    comment syntax to flag this inline, so note it here instead: the two numbers
    shown are a truncated preview, not the full vector -- showing that a value
    exists at all matters more than which two numbers they are. Other structures
    pass through unchanged.
    """
    if isinstance(obj, dict):
        return {k: elide_embedding_vectors(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj
        ):
            return obj[:2]
        return [elide_embedding_vectors(x) for x in obj]
    return obj


class ReadCommand(TodoFieldCommand):
    command_names = ("read",)
    doc_short: ClassVar[str] = "Print todo JSON"
    doc_long: ClassVar[str] = (
        "Read locates a TODO by full Id or by an unambiguous prefix of at least four hex "
        "characters. It searches the store first, then local and cached remote refs. "
        "Legacy field names are normalized and fields are "
        "ordered Id/Summary/Body first, Subtodos/WorkItems last. Every embedder with a stored vector "
        "for this todo is shown (cheap ones written at save time, expensive ones backfilled by "
        "search), merged in from the sqlite embeddings index regardless of which path wrote them. "
        "By default embedding vectors are elided to their first two elements; pass -v/--verbose to "
        "print them in full. The command prints the selected todo as formatted JSON to stdout."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register read arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
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
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        _merge_stored_embeddings(todo)
        payload: Any = order_ticket_fields(todo)
        if not self.verbose:
            payload = elide_embedding_vectors(payload)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0


class GetJsonPathCommand(TodoFieldCommand):
    command_names = ("get-json-path",)
    doc_short: ClassVar[str] = "Print a JSON path value"
    doc_long: ClassVar[str] = (
        "Get-json-path locates a todo by selector and prints one internal dot-path value as JSON. "
        "It is the low-level read primitive for scripts that should not inspect TODO.json directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register get-json-path arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("jsonpath", help="dot path, e.g. Body.raw or WorkItems.0.summary")

    def do(self) -> int:
        """Print a selected path value."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        print_json_value(get_at_path(todo, self.jsonpath))
        return 0


class ResolveUrlCommand(CorpusQueryCommand):
    command_names = ("resolveurl",)
    doc_short: ClassVar[str] = "Print the value a permalink addresses"
    doc_long: ClassVar[str] = (
        "Resolveurl dereferences a permalink -- /<todoid>/<path...> -- and prints the value it "
        "addresses, exactly as get-json-path would for the equivalent dot-path. It takes no "
        "selector: the todo is the first path segment. A full URL or a bare path both work, so a "
        "link pasted out of a browser resolves as-is. The first segment is any 4+ hex Id prefix; "
        "after it, a segment names a field case-insensitively (a list field ending in 's' also "
        "answers to the name minus that 's'), and a segment in front of a list is a where-clause "
        "whose default key is idx -- so a bare segment is always a 0-based index. The keys sha, "
        "subtodo_id and objid match on a 4+ character prefix. /<todoid>/objid/<prefix> addresses "
        "any object in the todo without naming its collection, and is the form to emit as a "
        "permalink: it survives edits to the work plan, which an index does not."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register resolveurl arguments."""
        parser.add_argument(
            "url",
            help="permalink: full URL or path, e.g. /8f3a2c1d/workitem/objid/0a3f",
        )

    def do(self) -> int:
        """Print the value the permalink addresses."""
        root = self.root()
        try:
            selector, segments = todo_url.split_url_path(self.url)
        except todo_url.TodoUrlError as exc:
            raise TodoError(str(exc)) from exc
        _, todo = resolve_ticket_by_id(root, selector)
        try:
            json_path = todo_url.to_json_path(todo, segments)
        except todo_url.TodoUrlError as exc:
            raise TodoError(f"{exc} (in todo {str(todo.get('Id', ''))[:8]})") from exc
        print_json_value(todo_url.value_at(todo, json_path))
        return 0


_GET_FIELD_PATHS: Dict[str, str] = {
    "summary": "Summary.raw",
    "body": "Body.raw",
    "ac": "AC",
    "state": "State",
    "actual_summary": "ActualSummary",
    "long_summary": "LongSummary.raw",
    "parent": "Parent",
    "tag": "Tag",
}


class GetCommand(TodoFieldCommand):
    command_names = ("get",)
    doc_short: ClassVar[str] = "Print one named todo field"
    doc_long: ClassVar[str] = (
        "Get is a friendly-field-name wrapper over get-json-path: pass exactly one of "
        "--summary/--body/--ac/--state/--actual-summary/--long-summary/--parent/--tag and it "
        "expands to the matching internal path (Summary.raw, Body.raw, AC, State, "
        "ActualSummary, LongSummary.raw, Parent, Tag respectively) and prints that value as JSON -- exactly like `get-json-path <selector> "
        "<path>` with the path already filled in. <selector> is an Id prefix or full digest. "
        "For any other path, or a nested value like WorkItems.0.summary, use get-json-path "
        "directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register get arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--summary", action="store_true", help="print Summary.raw")
        parser.add_argument("--body", action="store_true", help="print Body.raw")
        parser.add_argument("--ac", action="store_true", help="print AC")
        parser.add_argument("--state", action="store_true", help="print State")
        parser.add_argument(
            "--actual-summary", dest="actual_summary", action="store_true",
            help="print ActualSummary",
        )
        parser.add_argument(
            "--long-summary", dest="long_summary", action="store_true",
            help="print LongSummary.raw",
        )
        parser.add_argument("--parent", action="store_true", help="print Parent")
        parser.add_argument("--tag", action="store_true", help="print Tag")

    def do(self) -> int:
        """Print the one requested field, expanded to its internal path."""
        selected = [name for name in _GET_FIELD_PATHS if getattr(self, name)]
        if len(selected) != 1:
            raise TodoError(
                "pass exactly one of --summary, --body, --ac, --state, "
                "--actual-summary, --long-summary, --parent, --tag"
            )
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        print_json_value(get_at_path(todo, _GET_FIELD_PATHS[selected[0]]))
        return 0


class InitCommand(TodoCreateCommand):
    command_names = ("init",)
    edit_fields = ("summary", "body", "ac", "note", "actual_summary")
    doc_short: ClassVar[str] = "Create todo branch (run when ready to work)"
    doc_long: ClassVar[str] = (
        "Init makes a todo branch-bound and ready to work -- run it when the design is ready and "
        "you are about to WORK the todo. Two modes: (1) PROMOTE -- with --id naming an existing "
        "`groom` todo (created by `mint` and filled in with `set <id>`), it creates the git branch "
        "from that todo's finalized Branch label and moves it to state `ready`; (2) FRESH -- "
        "with --summary and no existing record, it mints (or accepts --id), writes the initial "
        "skeleton, and creates the branch, all in one call (backward-compatible). It refuses to "
        "create a second todo on a branch that already has one, and can optionally return to the "
        "parent branch (--stay-on-parent). For parent/context links use `set <id> --parent` "
        "after init. For the full subtodo lifecycle use add-subtodo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register init arguments."""
        parser.add_argument(
            "--summary",
            help="Summary.raw (required only when creating a fresh todo; a promoted "
            "groom todo already has one)",
        )
        parser.add_argument("--body", default="", help="Body.raw")
        parser.add_argument("--ac", default="", help="acceptance criteria")
        add_state_set_arguments(parser)
        parser.add_argument(
            "--id",
            help="promote the existing groom todo with this Id prefix; if no such "
            "record exists, use it as the pre-minted Id for a fresh create",
        )
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
        """Promote an existing groom todo, or create a fresh branch-bound todo.

        TODO(later): the State -> `init` transition here should move to a
        `--set-status init` path that also calls `ensure_worktree` to materialize
        the (possibly ephemeral) working tree for the branch. See the
        `ensure_worktree` subcommand. For now init sets `init` inline.
        """
        root = self.root()
        if read_todo_worktree(root) is not None:
            raise TodoError("todo already exists on current branch; resume it instead of init")

        # PROMOTE mode: --id names an existing (groom) record -> give it a
        # branch and move it to `init`, reusing the Branch `set` finalized.
        if self.id:
            existing = find_todos_by_id(root, self.id)
            if existing:
                if len(existing) > 1:
                    locations = ", ".join(loc for loc, _ in existing)
                    raise TodoError(f"ambiguous id {self.id!r}; matches on: {locations}")
                return self._promote(root, existing[0][1])

        return self._create_fresh(root)

    def _promote(self, root: Path, ticket: JsonDict) -> int:
        """Give an existing groom todo a git branch and move it to `ready`."""
        ticket_id = str(ticket["Id"])
        ticket = promote_groom_todo(
            root,
            ticket,
            branch=self.branch,
            stay_on_parent=self.stay_on_parent,
            no_commit=self.no_commit,
        )
        print(json.dumps({"Id": ticket_id, "Branch": ticket["Branch"]}, indent=2))
        return 0

    def _create_fresh(self, root: Path) -> int:
        """Mint (or accept --id), create branch, write skeleton, optionally commit."""
        if not self.summary:
            raise TodoError(
                "--summary is required to create a fresh todo "
                "(or pass --id of an existing groom todo to promote it)"
            )
        ticket_id: str = self.id or mint_id(root)
        branch: str = self.branch or kebab_branch_name(ticket_id, self.summary)
        if branch_exists(root, branch):
            raise TodoError(f"branch {branch!r} already exists")

        # Resolve any EDIT sentinels BEFORE creating the branch/ticket, so a
        # non-interactive EDIT aborts with nothing created (no todo to RM).
        self.resolve_edit_fields(ticket_id)

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
        base = head_sha(root)  # branch's initial sha (invariant #5)
        if base:
            ticket["BaseSha"] = base
        write_todo_worktree(root, ticket)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): init ticket {ticket_id[:8]}")
        # init-then-set: apply any set-style State/ActualSummary passed to init
        # (Summary/Body/AC already went into the skeleton above).
        if (
            self.state is not None
            or self.actual_summary is not None
            or self.long_summary is not None
        ):
            state = apply_set_fields(
                ticket,
                state=self.state,
                note=self.note,
                last_commit=self.last_commit,
                merged_into=self.merged_into,
                owner=self.owner,
                pr=self.pr,
                merge_commit=self.merge_commit,
                actual_summary=self.actual_summary,
                long_summary=self.long_summary,
            )
            if state in WORKTREE_TEARDOWN_STATES:
                assert_todo_worktree_removable(root, str(ticket.get("Branch") or ""))
            write_todo_worktree(root, ticket)
            if not self.no_commit:
                message = (
                    f"chore(todo): state -> {state}"
                    if state
                    else "chore(todo): update ticket fields"
                )
                commit_todo(root, message)
            teardown_worktree_for_terminal_state(root, ticket, state=state)
        if self.stay_on_parent and parent_branch:
            run_git(root, "checkout", parent_branch)
        print(json.dumps({"Id": ticket_id, "Branch": branch}, indent=2))
        return 0


class EnsureWorktreeCommand(SubtodoCommand):
    command_names = ("ensure_worktree",)
    doc_short: ClassVar[str] = "Ensure a linked git worktree exists for a todo"
    doc_long: ClassVar[str] = (
        "Ensure-worktree materializes a git working tree for the todo's branch under "
        "<todo-dir>/worktrees/<repo>/<branch>, creating it with `git worktree add` "
        "when absent. Idempotent when the branch already has a linked worktree. "
        "Fails (exit 1) when the ticket has no Branch or the branch does not exist "
        "yet unless --init is passed. With --init, runs the same promote as "
        "`init --id <selector> --stay-on-parent` when the branch is missing (noop "
        "when it already exists), then ensures the worktree. Selector is a 4+ hex "
        "Id prefix or the full digest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register ensure_worktree arguments."""
        parser.add_argument("todoid", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument(
            "--init",
            action="store_true",
            help="promote groom todo (todo init) when its git branch is missing; noop otherwise",
        )
        parser.add_argument(
            "--no-commit",
            action="store_true",
            help="with --init, skip the chore(todo) commit on the new branch",
        )

    def do(self) -> int:
        """Create or reuse the linked worktree for the todo's branch."""
        root = self.root()
        if self.init and read_todo_worktree(root) is not None:
            raise TodoError("todo already exists on current branch; resume it instead of init")
        _loc, todo = resolve_ticket_by_id(root, self.todoid)
        inited = False
        if self.init:
            todo, inited = maybe_init_todo_branch(
                root,
                todo,
                stay_on_parent=True,
                no_commit=self.no_commit,
            )
        payload = ensure_todo_worktree(root, todo)
        print(
            json.dumps(
                {
                    "Id": str(todo["Id"])[:8],
                    "Branch": str(todo.get("Branch") or ""),
                    "inited": inited,
                    **payload,
                },
                indent=2,
            )
        )
        return 0


class AddSubtodoCommand(SubtodoMergeCommand):
    command_names = ("add-subtodo",)
    doc_short: ClassVar[str] = "Create child todo"
    doc_long: ClassVar[str] = (
        "Add-subtodo creates a child TODO under the parent selected by <parent> (an Id prefix "
        "or full digest). It can load the child todo from JSON or build one from summary, body, "
        "and acceptance criteria. The child git branch is created at the tip of the parent's "
        "branch without checking anything out; both records are written through the store. It "
        "registers the child in the parent's Subtodos list so later merge bookkeeping can find it."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register add-subtodo arguments."""
        parser.add_argument("parent", help="parent todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--from-json", help="seed todo JSON (Id, Branch, fields)")
        parser.add_argument("--summary", help="Summary.raw when not using --from-json")
        parser.add_argument("--body", default="", help="Body.raw")
        parser.add_argument("--ac", default="", help="acceptance criteria")
        parser.add_argument("--id", help="pre-minted child Id")
        parser.add_argument("--branch", help="override Branch name")
        parser.add_argument("--path-from-root", help="Scope.path_from_root")

    def do(self) -> int:
        """Create a child branch + store record under the selected parent todo."""
        root = self.root()
        if not use_store():
            raise TodoError(
                "add-subtodo requires the store (sqlite or json-dir); "
                "legacy TODO_USE_JSON mode is import-only"
            )
        _, parent = resolve_ticket_by_id(root, self.parent)
        parent_branch = str(parent.get("Branch") or "")
        if not parent_branch:
            raise TodoError("parent ticket missing Branch")

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
        child_spec.setdefault("State", {"ready": {}})

        if branch_exists(root, child_branch):
            raise TodoError(f"branch {child_branch!r} already exists")

        base = run_git(
            root, "rev-parse", "--verify", "--quiet", parent_branch, check=False
        ).stdout.strip()
        if not base:
            raise TodoError(
                f"parent branch {parent_branch!r} not found here; "
                "init the parent (give it a branch) before adding subtodos"
            )
        # Child branch starts at the parent branch's tip; no checkout needed.
        run_git(root, "branch", child_branch, parent_branch)
        child_spec["BaseSha"] = base  # child branch's initial sha (invariant #5)
        write_todo_worktree(root, child_spec)

        upsert_subtodo(parent, child_spec)
        # Firing the subtodo completes the parent's cursor work item as a typed
        # start_subtodo done item and advances the cursor (invariants #1, #3).
        index = mark_cursor_done(parent, start_subtodo_workitem(child_id, summary=""))
        if not parent["WorkItems"][index].get("summary"):
            parent["WorkItems"][index]["summary"] = (
                f"start subtodo {child_id[:8]}: {_summary_snippet(raw_summary)}"
            )
        write_todo_worktree(root, parent)

        print(json.dumps({"Id": child_id, "Branch": child_branch, "Parent": parent_branch}, indent=2))
        return 0


class SetCommand(TodoFieldCommand):
    command_names = ("set",)
    doc_short: ClassVar[str] = "Patch todo fields / state"
    doc_long: ClassVar[str] = (
        "Set edits a todo's fields without changing branches. <selector> is required and is an "
        "Id prefix or full digest (works equally on a branch-bound todo or a branchless `groom` "
        "todo from `mint`). It updates Summary.raw, Body.raw, AC, ActualSummary, and/or the workflow State "
        "(--state, which replaces the removed `set-state` subcommand; State metadata "
        "--note/--last-commit/--merged-into/--owner ride along). "
        "Transitioning to done or merged tears down any linked git worktree for the todo's branch "
        "(refuses if that worktree is dirty). "
        "Pass --parent <id> (repeatable) as a make-it-so Parent list: the child's Parent becomes "
        "exactly those refs, follow-only INFO back-links are added on desired parents, and INFO "
        "back-links on former parents that are no longer listed are removed (tracked subtodos are "
        "never removed). Blank `--parent=` clears Parent. --tag/--untag (each repeatable) are "
        "aliases for the `tagadd`/`tagrm` subcommands -- see their help for the plural Tag "
        "field's manual/automatic semantics. To replace WorkItems or any other JSON "
        "path from a file or stdin, use set-json-path. The command requires at least one field "
        "change. The write is store-only (sqlite or json-dir backend): no branch checkout and "
        "no commit. For a `groom` todo, changing --summary also refreshes the Branch label so "
        "`init` later creates a well-named branch. Any free-text value passed as EDIT is "
        "captured from $VISUAL/$EDITOR/vi (interactive terminals only)."
    )
    edit_fields = ("summary", "body", "ac", "note", "actual_summary")

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set arguments."""
        parser.add_argument(
            "id",
            help="todo selector: Id prefix (4+ hex) or full digest -- required",
        )
        parser.add_argument("--summary")
        parser.add_argument("--body")
        parser.add_argument("--ac")
        add_state_set_arguments(parser)
        parser.add_argument(
            "--parent",
            action="append",
            metavar="PARENT_ID",
            help="make-it-so Parent list (repeatable Id prefixes); blank --parent= clears; "
            "syncs follow-only INFO back-links on parents",
        )
        parser.add_argument(
            "--tag",
            action="append",
            metavar="TAG",
            help="add a MANUAL tag (repeatable); alias for `tagadd` -- see its help",
        )
        parser.add_argument(
            "--untag",
            action="append",
            metavar="TAG",
            help="remove a MANUAL tag (repeatable); alias for `tagrm` -- see its help",
        )
        parser.add_argument("--no-commit", action="store_true")
        parser.add_argument(
            "--no-clear",
            action="store_true",
            help="keep existing embedding vectors even though raw text changed "
            "(for semantically trivial edits)",
        )

    def do(self) -> int:
        """Patch Summary/Body/AC/ActualSummary/Parent and/or State on a todo.

        <selector> is required and resolves by Id; the write is store-only.
        Committing would land a commit on whatever branch the caller happens
        to be on, so no record edit ever commits.
        """
        root = self.root()
        _loc, todo = resolve_ticket_by_id(root, self.id)
        self.resolve_edit_fields(str(todo.get("Id", "") or "current"))
        parent_touched = self.parent is not None
        tags_touched = bool(self.tag or self.untag)
        state = apply_set_fields(
            todo,
            summary=self.summary,
            body=self.body,
            ac=self.ac,
            state=self.state,
            note=self.note,
            last_commit=self.last_commit,
            merged_into=self.merged_into,
            owner=self.owner,
            pr=self.pr,
            merge_commit=self.merge_commit,
            actual_summary=self.actual_summary,
            long_summary=self.long_summary,
            parent_touched=parent_touched,
            tags_touched=tags_touched,
        )
        if parent_touched:
            apply_parent_links(root, todo, self.parent)
        if self.tag:
            apply_tag_add(todo, *self.tag)
        if self.untag:
            apply_tag_remove(todo, *self.untag)
        # While still collecting data (groom), keep the Branch label in sync
        # with the summary so `init` creates a well-named branch later.
        if self.summary is not None and current_state_name(todo) == "groom":
            new_branch = kebab_branch_name(str(todo["Id"]), self.summary)
            todo["Branch"] = new_branch
            if isinstance(todo.get("Scope"), dict):
                todo["Scope"]["branch"] = new_branch
        # done/merged tear down the linked worktree; refuse dirty trees first.
        if state in WORKTREE_TEARDOWN_STATES:
            assert_todo_worktree_removable(root, str(todo.get("Branch") or ""))
        write_todo_worktree(root, todo, no_clear=self.no_clear)
        if not self.no_commit:
            message = f"chore(todo): state -> {state}" if state else "chore(todo): update ticket fields"
            commit_todo(root, message)
        teardown_worktree_for_terminal_state(root, todo, state=state)
        if state:
            print(json.dumps(todo["State"], indent=2))
        return 0


class RmCommand(TodoFieldCommand):
    command_names = ("rm",)
    doc_short: ClassVar[str] = "Soft-delete a todo"
    doc_long: ClassVar[str] = (
        "Rm removes the todo identified by <todoid> (id or id-prefix) from the store. The default "
        "is a soft delete: a recoverable tombstone (a deleted_tickets row in a sqlite store, or an "
        "'<id>.deleted' file in a json-dir store) -- the same removal `export-to-file --remove` "
        "performs, without writing an export file. Pass --hard to delete permanently (no recovery "
        "tool exists). The git branch and any worktree are left intact."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register rm arguments."""
        parser.add_argument("todoid", help="id or id-prefix of the todo to remove")
        parser.add_argument(
            "--hard",
            action="store_true",
            help="permanently delete instead of leaving a recoverable tombstone",
        )

    def do(self) -> int:
        """Soft- (or, with --hard, hard-) delete the selected todo from the store."""
        store = todo_store.get_store()
        matches = store.find_by_id_prefix(self.todoid)
        if not matches:
            raise TodoError(f"no todo matches {self.todoid!r}")
        if len(matches) > 1:
            shorts = ", ".join(sorted({str(m[2].get("Id", ""))[:8] for m in matches}))
            raise TodoError(f"ambiguous selector {self.todoid!r}: {shorts}")
        todo = matches[0][2]
        tid = str(todo.get("Id") or "")
        removed = store.delete(todo, hard=self.hard)
        kind = "hard" if self.hard else "soft"
        print(f"{tid[:8]}  ({'removed: ' + kind if removed else 'not in store'})")
        return 0 if removed else 1


class TagAddCommand(TagCommand):
    command_names = ("tag-add",)
    doc_short: ClassVar[str] = "Add manual tag(s)"
    doc_long: ClassVar[str] = (
        "Tag-add adds one or more tags (repeatable) to the selected todo's plural Tag "
        "field as MANUAL elements: each is stripped, downcased, and deduped against any tag "
        "already present (manual or automatic) -- a no-op for one already there. The write is "
        "store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register tag-add arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("tags", nargs="+", metavar="TAG", help="tag(s) to add")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Add one or more manual tags to the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        apply_tag_add(todo, *self.tags)
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): tag +{', +'.join(self.tags)}")
        return 0


class TagRmCommand(TagCommand):
    command_names = ("tag-rm",)
    doc_short: ClassVar[str] = "Remove manual tag(s)"
    doc_long: ClassVar[str] = (
        "Tag-rm removes one or more tags (repeatable, case-insensitive) from the selected "
        "todo's plural Tag field. Only MANUAL elements are ever removed -- an automatic tag "
        "(manual: False, set by doctor's auto-tagging) is left alone even if named here, since "
        "those are doctor's to manage. Use tag-clear to drop automatic tags. The whole Tag "
        "field is dropped once it is empty. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register tag-rm arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("tags", nargs="+", metavar="TAG", help="tag(s) to remove")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Remove one or more manual tags from the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        apply_tag_remove(todo, *self.tags)
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): untag -{', -'.join(self.tags)}")
        return 0


class TagClearCommand(TagCommand):
    command_names = ("tag-clear",)
    doc_short: ClassVar[str] = "Clear tags (automatic by default)"
    doc_long: ClassVar[str] = (
        "Tag-clear drops tags wholesale, the counterpart to tag-add/tag-rm's per-tag edits. "
        "By default it removes only AUTOMATIC elements (manual: False) -- the ones doctor "
        "derives from Summary+Body, which are recomputed rather than curated and so are always "
        "safe to wipe. --all also removes MANUAL elements, which nothing will bring back. "
        "The selector is REQUIRED: either a specific todo (Id prefix or full digest) or the "
        "ALL sentinel to sweep the whole corpus -- a corpus-wide wipe has to be asked for "
        "by name, never defaulted into. Writes are store-only, and a todo with no matching "
        "tags is left untouched (no update_dt bump). Prints a JSON summary of what went."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register tag-clear arguments."""
        parser.add_argument(
            "selector",
            help="todo selector: Id prefix (4+ hex) or full digest, or ALL to sweep the "
            "whole corpus (required -- there is no default)",
        )
        parser.add_argument(
            "--all",
            dest="include_manual",
            action="store_true",
            help="also remove MANUAL tags (default: automatic tags only)",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Clear tags on one todo or across the corpus."""
        root = self.root()
        # (repo, todo) pairs: the store spans repos, so a corpus sweep must write
        # each record back under ITS OWN repo key, not this root's.
        targets: List[tuple[Optional[str], JsonDict]] = []
        if is_all_selector(self.selector):
            if not use_store():
                raise TodoError("ALL requires the db store (unset TODO_USE_JSON)")
            targets = [
                (repo, t) for repo, _branch, t in todo_store.get_store().list_located()
                if t.get("Id")
            ]
        else:
            _, todo = resolve_ticket_by_id(root, self.selector)
            targets = [(None, todo)]
        results: List[JsonDict] = []
        cleared = 0
        for repo, todo in targets:
            removed = apply_tag_clear(todo, include_manual=self.include_manual)
            if not removed:
                continue
            # A cleared tag takes its stamped vectors with it, so the positional
            # Tag.<i>.raw paths of whatever survives shift: write through
            # write_todo_worktree, which recomputes them (see _changed_raw_fields).
            write_todo_worktree(root, todo, repo=repo)
            cleared += 1
            results.append({"id": str(todo.get("Id", ""))[:8], "removed": removed})
        print(
            json.dumps(
                {
                    "include_manual": self.include_manual,
                    "scanned": len(targets),
                    "todos_cleared": cleared,
                    "tags_removed": sum(r["removed"] for r in results),
                    "results": results,
                },
                indent=2,
            )
        )
        if not self.no_commit and cleared:
            scope = "all" if self.include_manual else "auto"
            commit_todo(root, f"chore(todo): tag-clear ({scope}) on {cleared} todo(s)")
        return 0


class ClearSearchDataCommand(StoreMaintenanceCommand):
    command_names = ("clear-search-data",)
    doc_short: ClassVar[str] = "Drop derived search data (re-derived lazily)"
    doc_long: ClassVar[str] = (
        "Clear-search-data drops what SEARCH derived, which is safe precisely because "
        "none of it is source data: the next search recomputes whatever it needs. Two "
        "kinds go. Embedding vectors are removed from the embeddings index and from the "
        "stamped ticket JSON, and are backfilled again on the next search that selects "
        "that embedder. The DISCOVERED stopword list is removed from the todo dir's "
        "config.json, and the next search rediscovers it from the corpus as it stands "
        "then -- which is how you ask for a fresh list after the corpus has moved on, "
        "since discovery is otherwise sticky. The lexical index itself is not mentioned "
        "because it is never stored: tokenizing the corpus is cheap enough to redo per "
        "search, so only the expensive artifact earns storage. The selector is REQUIRED: "
        "a specific todo (Id prefix or full digest) or the ALL sentinel to sweep the "
        "corpus -- a corpus-wide wipe has to be asked for by name. The stopword list is "
        "corpus-level, so only ALL drops it; clearing one todo touches only its vectors. "
        "Prints a JSON summary of what went."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register clear-search-data arguments."""
        parser.add_argument(
            "selector",
            help="todo selector: Id prefix (4+ hex) or full digest, or ALL to sweep the "
            "whole corpus (required -- there is no default)",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Drop derived search data for one todo or across the corpus."""
        root = self.root()
        sweep = is_all_selector(self.selector)
        targets: List[tuple[Optional[str], JsonDict]] = []
        if sweep:
            if not use_store():
                raise TodoError("ALL requires the db store (unset TODO_USE_JSON)")
            targets = [
                (repo, t) for repo, _branch, t in todo_store.get_store().list_located()
                if t.get("Id")
            ]
        else:
            _, todo = resolve_ticket_by_id(root, self.selector)
            targets = [(None, todo)]

        store = todo_store.get_store()
        cleared = 0
        vectors_removed = 0
        for repo, todo in targets:
            ticket_id = str(todo.get("Id", ""))
            if not ticket_id:
                continue
            stamped = _json_embeddings_present(todo)
            for field_path in {path for path, _fingerprint in stamped}:
                _strip_vectors_at(todo, field_path)
            store.clear_embeddings(ticket_id)
            if not stamped:
                continue
            # no_clear: the raws did not change, so there is nothing stale to
            # re-clear -- and clearing again would just redo what we did here.
            write_todo_worktree(root, todo, no_clear=True, repo=repo)
            cleared += 1
            vectors_removed += len(stamped)

        stopwords_cleared = False
        if sweep and todo_store.config_list(todo_db.todo_dir(), SEARCH_STOPWORDS_KEY):
            todo_store.update_config(todo_db.todo_dir(), {SEARCH_STOPWORDS_KEY: None})
            stopwords_cleared = True

        print(
            json.dumps(
                {
                    "scanned": len(targets),
                    "todos_cleared": cleared,
                    "vectors_removed": vectors_removed,
                    "stopwords_cleared": stopwords_cleared,
                },
                indent=2,
            )
        )
        if not self.no_commit and cleared:
            commit_todo(root, f"chore(todo): clear-search-data on {cleared} todo(s)")
        return 0


class WorkItemAddCommand(WorkItemEditCommand):
    command_names = ("work-item-add",)
    doc_short: ClassVar[str] = "Append work item"
    doc_long: ClassVar[str] = (
        "Work-item-add appends a new open WorkItems entry to the selected todo. The entry stores "
        "the provided summary and starts with done set to false. Existing work items keep their "
        "order and content. The write is store-only, so it works equally on a branchless groom "
        "todo (incremental plan seeding) and a branch-bound one."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-add arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Append a not-done task work item to the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        work_items: List[JsonDict] = list(todo.get("WorkItems") or [])
        work_items.append({"kind": WORKITEM_TASK, "summary": self.summary, "done": False})
        todo["WorkItems"] = work_items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): add work item: {_summary_snippet(self.summary)}")
        return 0


class WorkItemDoneCommand(WorkItemProgressCommand):
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
        "cursor task's summary). --checkpoint completes a NO-COMMIT item (recon, waits, "
        "bookkeeping) instead: clean tree only, records HEAD observationally as at_sha (never as "
        "attribution), message = -m. --blocked completes an item that CANNOT be done as written "
        "(the approach turned out to be impossible, or the data it needs does not exist): clean "
        "tree only, records the no-change sentinel sha, and requires -m -- the long form of what "
        "was tried, what was found, and what the options are. Like State metadata, inapplicable "
        "flags raise: -m on a clean tree without --checkpoint/--blocked, --sha with either, or "
        "both variants together, are errors rather than silent no-ops."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-done arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("-m", "--message", help="commit message for a dirty tree (defaults to the work item summary); with --checkpoint, the recorded no-op message")
        parser.add_argument("--sha", help="commit sha for a clean tree; must equal HEAD")
        parser.add_argument("--summary", help="override the work item's high-level description")
        parser.add_argument(
            "--checkpoint",
            action="store_true",
            help="complete as a no-commit checkpoint: records HEAD as observational at_sha; clean tree only",
        )
        parser.add_argument(
            "--blocked",
            action="store_true",
            help="complete as BLOCKED (cannot be done as written): records the no-change sentinel sha; requires -m; clean tree only",
        )

    def do(self) -> int:
        """Complete the cursor work item as code (invariant #1).

        Post-condition: the branch is fully committed. A clean tree records the
        current HEAD; a dirty tree commits all updates and new files first."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        # The recorded sha must land on the todo's own branch, so the CWD must
        # be a checkout (worktree) of that branch -- unlike pure record edits,
        # which are store-only and work from anywhere.
        branch = str(todo.get("Branch") or "")
        checked_out = current_branch(root)
        if checked_out != branch:
            raise TodoError(
                f"work-item-done commits code on the todo's branch {branch!r}; "
                f"run it from a checkout of that branch (currently on {checked_out!r})"
            )
        dirty = bool(run_git(root, "status", "--porcelain", check=False).stdout.strip())
        if self.checkpoint and self.blocked:
            raise TodoError(
                "--checkpoint and --blocked are different completions: a no-commit step that "
                "FINISHED versus one that cannot be done as written; pass one"
            )
        if self.blocked:
            # The item cannot be completed as written. The LONG form of why belongs
            # here, on the item: the State note is read once by the user deciding
            # what to do next, while the WorkItems trail is what a future agent
            # walks -- so the narrative has to survive in the trail. Same per-variant
            # metadata discipline as --checkpoint: inapplicable flags raise.
            # A blocked item left LAST makes the todo is-done with no real final
            # commit; doctor rejects that under #6 rather than this command, since
            # a later item may still be added.
            if self.sha:
                raise TodoError(
                    "--blocked does not take --sha; it records the no-change sentinel "
                    "(a blocked item produced no commit)"
                )
            if not self.message:
                raise TodoError(
                    "--blocked requires -m: the long form of what was tried, what was found, "
                    "and what the options are -- a bare 'blocked' teaches the next agent nothing"
                )
            if dirty:
                raise TodoError(
                    "--blocked records no commit but the tree is dirty; commit the partial "
                    "attempt (plain work-item-done) or clean the tree first"
                )
            item = code_workitem(
                WORKITEM_NULL_SHA, summary=self.summary or "", message=self.message
            )
            index = mark_cursor_done(todo, item)
            write_todo_worktree(root, todo)
            node = todo["WorkItems"][index]
            print(
                json.dumps(
                    {
                        "index": index,
                        "kind": WORKITEM_CODE,
                        "sha": node["sha"],
                        "summary": node.get("summary", ""),
                        "message": node["message"],
                    },
                    indent=2,
                )
            )
            return 0
        if self.checkpoint:
            # No-commit completion. Per-variant metadata discipline (same doctrine
            # as set_state): flags the variant does not keep are errors.
            if self.sha:
                raise TodoError(
                    "--checkpoint does not take --sha; it records HEAD as observational at_sha"
                )
            if dirty:
                raise TodoError(
                    "--checkpoint records no commit but the tree is dirty; commit the work "
                    "(plain work-item-done) or clean the tree first"
                )
            head = head_sha(root)
            if not head:
                raise TodoError("no commits on branch; cannot record a checkpoint position")
            item = checkpoint_workitem(
                str(head), summary=self.summary or "", message=self.message or ""
            )
            index = mark_cursor_done(todo, item)
            write_todo_worktree(root, todo)
            node = todo["WorkItems"][index]
            print(
                json.dumps(
                    {
                        "index": index,
                        "kind": WORKITEM_CHECKPOINT,
                        "at_sha": node["at_sha"],
                        "summary": node.get("summary", ""),
                        "message": node["message"],
                    },
                    indent=2,
                )
            )
            return 0
        if dirty:
            if self.sha:
                raise TodoError("--sha is not allowed with a dirty tree; a new commit will be made")
            message = self.message or self.summary or cursor_summary(todo) or "work-item-done"
            run_git(root, "add", "-A")
            run_git(root, "commit", "-m", message)
            sha = head_sha(root)
        else:
            if self.message:
                # Silently dropping -m would make it look like it took effect
                # (the node would instead inherit HEAD's own commit message).
                raise TodoError(
                    "-m does nothing on a clean tree (the HEAD commit's own message is "
                    "recorded); commit the work first, or pass --checkpoint for a "
                    "no-commit item, or --blocked for one that cannot be done as written"
                )
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


class WorkItemReadCommand(WorkItemProgressCommand):
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
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")

    def do(self) -> int:
        """Print the cursor work item for the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
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


class WorkItemInsertCommand(WorkItemEditCommand):
    command_names = ("work-item-insert",)
    doc_short: ClassVar[str] = "Insert a task at the cursor"
    doc_long: ClassVar[str] = (
        "Work-item-insert adds a not-done task at the cursor so it becomes the current item, "
        "pushing the existing frontier down (used to explode a step into finer steps). It appends "
        "when the todo has no open item. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-insert arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Insert a not-done task at the cursor."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
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


class WorkItemReplaceCommand(WorkItemEditCommand):
    command_names = ("work-item-replace",)
    doc_short: ClassVar[str] = "Replace the cursor work item"
    doc_long: ClassVar[str] = (
        "Work-item-replace rewrites the current (cursor) task's freetext summary, leaving it "
        "not-done. Errors when there is no open item. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-replace arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Replace the cursor task's summary."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
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


class WorkItemDeleteCommand(WorkItemEditCommand):
    command_names = ("work-item-delete",)
    doc_short: ClassVar[str] = "Delete the cursor work item"
    doc_long: ClassVar[str] = (
        "Work-item-delete removes the current (cursor) not-done item. Done items are the "
        "committed history of the todo and are never the cursor, so they are never deleted here. "
        "Errors when there is no open item. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-delete arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Delete the cursor work item."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
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


class IsDoneCommand(WorkItemProgressCommand):
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
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")

    def do(self) -> int:
        """Print and return the todo's done state."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        done = is_done(todo)
        print(json.dumps({"id": str(todo.get("Id", ""))[:8], "is_done": done}, indent=2))
        return 0 if done else 1


class LastShaCommand(WorkItemProgressCommand):
    command_names = ("last-sha",)
    doc_short: ClassVar[str] = "Print the last work item sha"
    doc_long: ClassVar[str] = (
        "Last-sha prints the sha of the selected todo's last work item, which is the last commit "
        "on its branch (invariant #6). Errors when the todo has no completed code/merge tail."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register last-sha arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")

    def do(self) -> int:
        """Print the last work item's sha."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        sha = last_sha(todo)
        if not sha:
            raise TodoError("no work item sha (todo has no completed code/merge tail)")
        print(sha)
        return 0


class SetJsonPathCommand(TodoFieldCommand):
    command_names = ("set-json-path",)
    doc_short: ClassVar[str] = "Set a JSON path from stdin or file"
    doc_long: ClassVar[str] = (
        "Set-json-path sets any JSON path on a selected todo (e.g. WorkItems, Body.raw, "
        "WorkItems.0.summary) to a value read as JSON from --file, or from stdin by default. The "
        "input must be valid JSON. The selector targets the todo by Id through the store and the "
        "write is store-only (no branch checkout, no commit), exactly like `set` -- so it works "
        "on a branchless `groom` todo (e.g. seeding WorkItems on a freshly minted plan). This is "
        "the general way to replace WorkItems or seed a whole plan. (--stay is a retained no-op: "
        "no checkout happens.)"
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set-json-path arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
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


class MergeSubtodoCommand(SubtodoMergeCommand):
    command_names = ("merge-subtodo",)
    doc_short: ClassVar[str] = "Record child merge"
    doc_long: ClassVar[str] = (
        "Merge-subtodo records that a child todo has been merged into its parent. It verifies "
        "the child todo is done or already merged, locates the parent through the child's "
        "Parent[0] ref, and updates both records through the store -- no branch is checked out. "
        "The recorded merge sha is the tip of the parent's branch (the caller's actual git "
        "merge, which must already have landed). The command prints a small JSON merge summary."
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


class WaitForCommand(SubtodoWaitCommand):
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


class WaitAndMergeCommand(SubtodoWaitCommand):
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


def _recompute_auto_tags(todo: JsonDict) -> int:
    """Recompute AUTOMATIC Tag elements for *todo* in place; return how many were set.

    DORMANT as shipped: there is no cheap embedder registered any more (the
    lexical ``hash`` backend that used to fill that slot was removed precisely
    because it made these tags collision noise rather than topics), so
    ``cheap_embedders()`` is empty and this returns 0 without touching *todo*.
    It re-arms by itself once a cheap SEMANTIC backend is registered -- the
    successor work is ticket 91e28fd0's domain-tuned importance pipeline, which
    should also settle the hubness correction and word-level (rather than
    sentence-level) candidates before this is trusted again.

    When armed: trusts any AUTOMATIC (``manual: False``) elements already
    present and does nothing (a cheap no-op) -- the same
    trust-existing/backfill-empty policy used elsewhere for embeddings, so a
    normal doctor run stays cheap. MANUAL elements are always kept. Otherwise
    mines the tag candidate domain from the whole corpus (``_load_corpus`` +
    ``_mine_tag_candidates``) and scores it against this todo's Summary+Body
    text (``compute_auto_tags``) using the first cheap embedder. Tolerates a
    missing/failing embedder, an empty corpus, or an embedder error by doing
    nothing, so a broken embedder never crashes doctor.
    """
    existing = todo.get("Tag")
    elements = existing if isinstance(existing, list) else []
    if any(isinstance(e, dict) and e.get("manual") is False for e in elements):
        return 0
    text = " ".join(
        raw for raw in (_raw_of(todo, "Summary"), _raw_of(todo, "Body")) if raw
    )
    if not text:
        return 0
    try:
        embedders = todo_embed.cheap_embedders()
        if not embedders:
            return 0
        store = todo_store.get_store()
        _tickets, raws = _load_corpus(store)
        candidates = _mine_tag_candidates(raws)
        if not candidates:
            return 0
        auto = compute_auto_tags(text, candidates, embedders[0], _AUTO_TAG_K)
    except (ValueError, RuntimeError):
        return 0
    if not auto:
        return 0
    manual = [e for e in elements if isinstance(e, dict) and e.get("manual") is True]
    todo["Tag"] = manual + auto
    return len(auto)


# --- gh / pull-request reconciliation ---------------------------------------
#
# Pushing a PR hands this branch's contents off to another entity, which is the
# same thing `merged` already means for a subtodo absorbed by its parent -- so a
# ROOT todo whose branch went to a PR is `merged {"pr": N}`. The PR's fate then
# refines that: a merged PR records its merge commit, a closed-unmerged PR becomes
# `rejected`. Doctor reconciles in both directions, so a PR opened by hand in the
# GitHub UI (which this CLI never saw) is still discovered and filled in.
#
# gh is attempted ONCE per process. The first ENVIRONMENTAL failure (missing
# binary, no auth, no network, rate limit) disables it for the rest of the run and
# records the reason plus its remediation, so a `doctor ALL` sweep reports one
# actionable line instead of repeating the same failure per todo. A per-repo
# failure (unknown repo, no access) skips only that todo -- it says nothing about
# whether gh works.
_GH_GATE: Dict[str, Optional[str]] = {"disabled": None}

# owner/repo out of a git remote URL: git@host:owner/repo.git,
# https://host/owner/repo.git, ssh://git@host/owner/repo
_GH_SLUG_RE = re.compile(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?/?$")

# States whose disposition a PR can still refine. `done` is included because a
# PR may have been opened by hand after the todo was closed out.
_PR_RECONCILABLE = frozenset({"done", "merged", "rejected"})


def gh_reset_gate() -> None:
    """Re-arm the once-per-run gh gate (test seam; a fresh process starts armed)."""
    _GH_GATE["disabled"] = None


def gh_gate_reason() -> Optional[str]:
    """Return why gh is disabled for this run, or None while it is still armed."""
    return _GH_GATE["disabled"]


def gh_repo_slug(todo: JsonDict, root: Path) -> Optional[str]:
    """Best-effort ``owner/repo`` for ``gh -R``, or None when it is not GitHub.

    Prefers the todo's own ``Scope.git_url`` so a cross-repo store still resolves
    the right repo, and falls back to the current repo's origin.
    """
    scope = todo.get("Scope")
    url = scope.get("git_url") if isinstance(scope, dict) else None
    if not isinstance(url, str) or not url:
        url = git_url_for_repo(root)
    if not isinstance(url, str) or "github" not in url.lower():
        return None
    match = _GH_SLUG_RE.search(url.strip())
    return match.group(1) if match else None


def run_gh(*args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    """Run a gh command, turning a missing binary or timeout into a failed result."""
    try:
        return subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False, timeout=timeout
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(["gh", *args], returncode=127, stdout="", stderr=str(exc))
    except OSError as exc:
        return subprocess.CompletedProcess(["gh", *args], returncode=1, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            ["gh", *args], returncode=124, stdout="", stderr=f"gh timed out after {timeout}s"
        )


def _gh_classify(result: subprocess.CompletedProcess[str]) -> tuple[str, str, bool]:
    """Map a failed gh run to ``(reason, remediation, environmental)``.

    *environmental* True means the failure is about this machine or session rather
    than one repo, so it disables gh for the rest of the run.
    """
    stderr = (result.stderr or "").strip()
    low = stderr.lower()
    if result.returncode == 127 or "no such file" in low:
        return ("gh is not installed", "install the GitHub CLI: brew install gh", True)
    if result.returncode == 124:
        return (stderr or "gh timed out", "check network/VPN, then re-run doctor", True)
    if "auth login" in low or "authentication" in low or "not logged in" in low:
        return ("gh is not authenticated", "run: gh auth login", True)
    if "rate limit" in low:
        return ("GitHub API rate limit reached", "wait for the reset, or check: gh auth status", True)
    for token in ("could not resolve host", "dial tcp", "connection refused", "network is unreachable"):
        if token in low:
            return ("cannot reach GitHub", "check network/VPN, then re-run doctor", True)
    if "could not resolve to a repository" in low or "not found" in low:
        return ("repo not found or no access", "check the repo slug and: gh auth status", False)
    first = stderr.splitlines()[0] if stderr else f"gh exited {result.returncode}"
    return (f"gh failed: {first}", "run the gh command by hand to see the full error", False)


def _gh_json(*args: str) -> tuple[Any, Optional[str]]:
    """Run a gh command expecting JSON on stdout; return ``(payload, skip_reason)``.

    An environmental failure trips the once-per-run gate; every later call short
    circuits on that recorded reason instead of retrying.
    """
    disabled = _GH_GATE["disabled"]
    if disabled:
        return (None, f"gh disabled this run ({disabled})")
    result = run_gh(*args)
    if result.returncode != 0:
        reason, remediation, environmental = _gh_classify(result)
        message = f"{reason} -- {remediation}"
        if environmental:
            _GH_GATE["disabled"] = message
        return (None, message)
    try:
        return (json.loads(result.stdout or "null"), None)
    except json.JSONDecodeError:
        return (None, "gh returned unparseable JSON -- run the gh command by hand")


def recorded_pr(todo: JsonDict) -> Optional[int]:
    """The PR number this todo's State already records, or None.

    Distinguishes a PR handoff (`merged {"pr": N}`) from a plain branch handoff
    (`merged {"merged_into": "some-branch"}`), which records no PR at all.
    """
    state = todo.get("State")
    if not isinstance(state, dict):
        return None
    value = next(iter(state.values()), None)
    if isinstance(value, dict) and isinstance(value.get("pr"), int):
        return value["pr"]
    return None


def gh_pr_for_todo(todo: JsonDict, root: Path) -> tuple[Optional[JsonDict], Optional[str]]:
    """Return ``(pr, skip_reason)`` for this todo's branch or recorded PR number.

    Looks the PR up by its recorded number when the State carries one (so a
    renamed or deleted branch still reconciles), else discovers one from the
    branch head -- which is how a hand-opened PR gets noticed.
    """
    slug = gh_repo_slug(todo, root)
    if not slug:
        return (None, "no GitHub remote for this todo")
    fields = "number,state,mergeCommit,baseRefName,url"
    recorded = recorded_pr(todo)
    if recorded is not None:
        payload, skip = _gh_json("pr", "view", str(recorded), "-R", slug, "--json", fields)
        if skip:
            return (None, skip)
        return (payload if isinstance(payload, dict) else None, None)
    branch = todo.get("Branch")
    if not isinstance(branch, str) or not branch:
        return (None, "todo has no Branch to search for a PR")
    payload, skip = _gh_json(
        "pr", "list", "-R", slug, "--head", branch, "--state", "all",
        "--json", fields, "--limit", "1",
    )
    if skip:
        return (None, skip)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return (payload[0], None)
    return (None, None)  # no PR exists yet; not an error


def reconcile_pr_state(root: Path, todo: JsonDict, *, dry_run: bool) -> JsonDict:
    """Reconcile a todo's terminal disposition against its PR's fate on GitHub.

    Skipped only for a genuinely TRACKED subtodo (created via `add-subtodo`):
    its ``merged`` records absorption into its parent's branch via
    `merge-subtodo`, which has nothing to do with a PR and must never be
    overwritten here. A todo whose `Parent` is only an informational back-link
    (`set --parent`) is NOT a tracked subtodo and is reconciled normally --
    having *any* `Parent` entry is not by itself grounds to skip; see
    `child_is_tracked_subtodo`. Returns a summary dict; ``changed`` is True
    only when State moved (and was written, unless *dry_run*).
    """
    out: JsonDict = {"checked": False, "changed": False}
    name = current_state_name(todo)
    if name not in _PR_RECONCILABLE:
        return out
    if child_is_tracked_subtodo(root, todo):
        out["skipped"] = "subtodo: `merged` here means parent-absorbed, not a PR"
        return out
    pr, skip = gh_pr_for_todo(todo, root)
    if skip:
        out["skipped"] = skip
        return out
    out["checked"] = True
    if pr is None:
        # Only a state that actually names a PR is suspicious when gh cannot find
        # it. `merged {merged_into: <branch>}` on a root todo is a plain branch
        # handoff (a direct merge or cherry-pick) and needs no PR at all.
        missing = recorded_pr(todo)
        if missing is not None:
            out["warning"] = f"State records pr #{missing} that gh cannot find"
        return out
    number = pr.get("number")
    gh_state = str(pr.get("state") or "").upper()
    out["pr"] = number
    out["gh_state"] = gh_state
    out["from"] = name
    commit = pr.get("mergeCommit")
    sha = commit.get("oid") if isinstance(commit, dict) else None
    if gh_state == "MERGED":
        target, kwargs = "merged", {"pr": number, "merge_commit": sha, "merged_into": pr.get("baseRefName")}
    elif gh_state == "CLOSED":
        target, kwargs = "rejected", {"pr": number, "note": f"PR #{number} closed without merging"}
    else:  # OPEN (or DRAFT): the handoff happened, its fate is undecided
        target, kwargs = "merged", {"pr": number}
    before = json.dumps(todo.get("State"), sort_keys=True)
    candidate = dict(todo)
    set_state(candidate, target, **kwargs)
    out["to"] = target
    if json.dumps(candidate["State"], sort_keys=True) == before:
        return out
    out["changed"] = True
    if not dry_run:
        todo["State"] = candidate["State"]
        todo["update_dt"] = utc_now()
        write_todo_worktree(root, todo)
    return out


def _doctor_one(root: Path, selector: str, *, dry_run: bool) -> JsonDict:
    """Audit one todo and (unless dry_run) repair its parent back-links + auto tags.

    Repair walks the audited todo's `Parent` refs and re-establishes a
    follow-only INFO back-link on each parent -- healing links that were
    one-way (legacy links) or lost, and refreshing INFO summaries. It also
    recomputes AUTOMATIC Tag elements when none are present yet (see
    ``_recompute_auto_tags``), persisting the todo only when that adds any, and
    reconciles a root todo's terminal disposition against its PR's fate on GitHub
    (see ``reconcile_pr_state``). A gh failure is reported as a warning carrying
    its remediation, never a hard finding. Also tears down a leftover linked
    worktree when State is done/merged.
    """
    _loc, todo = resolve_ticket_by_id(root, selector)
    findings = doctor_findings(root, selector)
    warnings = doctor_warnings(root, selector)
    repairs = reestablish_backlinks(root, todo, dry_run=dry_run)
    if current_state_name(todo) in WORKTREE_TEARDOWN_STATES:
        branch = str(todo.get("Branch") or "")
        leftover = worktree_path_for_branch(root, branch) if branch else None
        if leftover is not None:
            if dry_run:
                repairs.append(f"would remove worktree {leftover}")
            else:
                try:
                    removed = remove_todo_worktree_for_branch(root, branch)
                    if removed:
                        repairs.append(f"removed worktree {removed}")
                        # Re-audit so ok/findings reflect the teardown.
                        findings = doctor_findings(root, selector)
                except TodoError as exc:
                    findings.append(str(exc))
    # Read-only, so it runs under --dry-run too: reporting the disposition doctor
    # WOULD write is the point of a dry run.
    pr = reconcile_pr_state(root, todo, dry_run=dry_run)
    if pr.get("warning"):
        warnings.append(f"PR: {pr['warning']}")
    auto_tags = 0
    if not dry_run:
        auto_tags = _recompute_auto_tags(todo)
        if auto_tags:
            write_todo_worktree(root, todo)
    return {
        "id": str(todo.get("Id", ""))[:8],
        "ok": not findings,
        "findings": findings,
        "warnings": warnings,
        "repairs": repairs,
        "pr": pr,
        "auto_tags": auto_tags,
    }


class DoctorCommand(StoreMaintenanceCommand):
    command_names = ("doctor",)
    doc_short: ClassVar[str] = "Audit and repair todo health"
    doc_long: ClassVar[str] = (
        "Doctor audits a todo -- selector resolution, top-level schema, State shape, Subtodos "
        "references, and wait-graph sanity -- and repairs parent back-links: for each of the "
        "todo's --parent references it re-establishes a follow-only INFO back-link in the parent's "
        "Subtodos (best-effort, same-repo, store only). Repair also removes a leftover linked "
        "worktree when State is done or merged. Repair runs by default; pass --dry-run to "
        "audit and report intended repairs without writing. Repair also clears every stale per-TODO "
        "lock left by a crashed writer (reported as 'unlocked'). It also brings the store's records "
        "up to the latest schema opportunistically (the migrate-to-latest sweep -- a cheap no-op when "
        "already current), reported as 'migrated'. It also recomputes AUTOMATIC Tag elements for an "
        "audited todo that has none yet (trusting any already present, so a normal run is cheap), "
        "reported as 'auto_tags'. For a ROOT todo in a terminal state it reconciles the PR "
        "disposition via gh (reported as 'pr'): a done todo with a PR becomes merged {pr}, a merged "
        "PR records its merge_commit, a closed-unmerged PR becomes rejected. gh is attempted once "
        "per run -- the first environmental failure disables it for the rest of the run and reports "
        "the reason plus its remediation under 'gh'. Pass the ALL sentinel as the selector to sweep "
        "the whole corpus instead of a single selector. Exit 1 when any hard finding is present."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register doctor arguments."""
        parser.add_argument(
            "selector",
            help="todo selector (Id prefix or full digest) to audit, or ALL to sweep the whole corpus",
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
        if not self.dry_run and use_store():
            unlocked = todo_store.get_store().force_unlock_all()
        # Opportunistic schema sweep: bringing the store's records up to the
        # latest schema is maintenance, so doctor owns it -- not a bespoke command
        # a human must remember. Cheap when current (one data_version read) and
        # only sweeps when behind; --dry-run audits without mutating.
        migrated = 0
        if not self.dry_run:
            store = todo_store.get_store()
            if store.get_data_version() < todo_db.SCHEMA_VERSION:
                migrated = migrate_store(store)["migrated"]
        if is_all_selector(self.selector):
            if not use_store():
                raise TodoError("ALL requires the db store (unset TODO_USE_JSON)")
            ids = [str(t.get("Id", "")) for t in todo_store.get_store().list_all()]
            results = [_doctor_one(root, tid, dry_run=self.dry_run) for tid in ids if tid]
            ok = all(r["ok"] for r in results)
            print(
                json.dumps(
                    {
                        "ok": ok,
                        "dry_run": self.dry_run,
                        "unlocked": unlocked,
                        "migrated": migrated,
                        "auto_tags": sum(r["auto_tags"] for r in results),
                        "pr_reconciled": sum(1 for r in results if r["pr"].get("changed")),
                        "gh": gh_gate_reason() or "ok",
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
                    "migrated": migrated,
                    "auto_tags": result["auto_tags"],
                    "pr": result["pr"],
                    "gh": gh_gate_reason() or "ok",
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
        "State": {str(entry.get("State", "ready")): {}},
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
    if len(cid) >= 4 and use_store():
        for _repo_path, _branch, todo in todo_store.get_store().find_by_id_prefix(cid[:8]):
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


class LogCommand(CorpusQueryCommand):
    command_names = ("log",)
    doc_short: ClassVar[str] = "Show todo graph (oneline, from TODO.json)"
    doc_long: ClassVar[str] = (
        "Log renders the todo graph derived from TODO.json Subtodos relationships in "
        "git-log --graph --oneline style: one line per todo as "
        "'* <Id[0:8]> <summary>  [<state>]', with vertical rails for the subtodo tree. The "
        "graph is read entirely from TODO.json files through todo.py's own readers, never "
        "from git history. Selector is a 4+ hex Id prefix, the full digest, or the ALL "
        "sentinel; ALL renders every discoverable todo as a forest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register log arguments."""
        parser.add_argument(
            "selector",
            help="todo selector: Id prefix (4+ hex), full digest, or ALL",
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
        if is_all_selector(self.selector):
            roots = forest_roots(root)
            if not roots:
                raise TodoError("no TODO.json tickets found in this repo")
        else:
            _loc, ticket = resolve_ticket_by_id(root, self.selector)
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


class WebCommand(EnvironmentCommand):
    command_names = ("web",)
    doc_short: ClassVar[str] = "Serve todo viewer"
    doc_long: ClassVar[str] = (
        "Web serves a viewer for a todo. Above a movable split it shows the todo's Id, Summary, "
        "Body, work items (horizontal boxes) and subtodos (horizontal boxes). Clicking a work "
        "item shows its full commit message and diff below the split and highlights any subtodo "
        "it references; clicking a subtodo highlights the work items that reference it and shows "
        "a read-only rendition below the split. Clicking anything rewrites the address bar to "
        "that item's permalink, so what is on screen is always copyable. With a selector (a 4+ "
        "hex Id prefix) the printed URL opens straight onto that todo; without one the page is a "
        "vector search (the same ranking as 'todo search') over every todo, showing update-time "
        "and State columns, with an empty query listing all. It also serves permalinks: "
        "/<todoid>/<path...> renders the whole todo focused on the object that path resolves to "
        "(see 'resolveurl' for the grammar)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register web viewer arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default=None,
            help="todo selector: 4+ hex Id prefix or full digest (default: search page)",
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
        # Header label: the storage anchor (same value `todo basedir` prints),
        # not the current worktree gitroot. The store is shared across all
        # worktrees, so labelling the page with this worktree misrepresents it.
        # `root` still drives git ops (diffs/selectors) below -- only the label moves.
        basedir = todo_db.todo_dir()

        def resolve_todo(selector: str) -> tuple[Path, JsonDict]:
            """Resolve an ?id= selector to (repo_root, todo) for the viewer.

            The concrete repo is always the CWD; git failures for a todo whose
            commits are not present here render as 'diff unavailable'.
            """
            try:
                ticket = resolve_ticket_by_id(root, selector)[1]
            except TodoError as exc:
                raise todo_web.TodoWebError(str(exc)) from exc
            return root, ticket

        def list_todos() -> List[JsonDict]:
            """Every todo in the store -- no repo scoping, no filtering."""
            if not use_store():
                return list(discover_all_tickets(root).values())
            return [normalize_todo_schema(t) for t in todo_store.get_store().list_all()]

        def search_rows(query: str) -> List[JsonDict]:
            """Structured rows for the viewer's search box.

            A non-empty query runs the same vector search as `todo search`
            (rank order preserved); an empty query lists every todo. The box has
            no shell, so it is split with ``shlex`` -- a quoted phrase becomes one
            term, mirroring the CLI (unbalanced quotes fall back to whitespace
            splitting). Rows carry state/update-time so the page can render the
            -tu/-s columns.
            """
            if query.strip():
                try:
                    terms = shlex.split(query)
                except ValueError:
                    terms = query.split()
                if terms:
                    try:
                        rows, _hidden = run_search(root, terms)
                        return rows
                    except TodoError as exc:
                        raise todo_web.TodoWebError(str(exc)) from exc
            return [todo_row(todo) for todo in list_todos()]

        initial_id: Optional[str] = None
        if self.selector is not None:
            _, ticket = resolve_ticket_by_id(root, self.selector)
            initial_id = str(ticket.get("Id") or "") or None

        try:
            if self.dump_html:
                if initial_id is not None:
                    todo_root, ticket = resolve_todo(initial_id)
                    print(todo_web.render_todo_page(todo_root, ticket))
                else:
                    print(todo_web.render_search_page(basedir, search_rows("")))
            else:
                todo_web.serve(
                    basedir,
                    host=self.host,
                    port=self.port,
                    initial_id=initial_id,
                    resolver=resolve_todo,
                    searcher=search_rows,
                )
        except todo_web.TodoWebError as exc:
            raise TodoError(str(exc)) from exc
        return 0


class ImportJsonCommand(StoreMaintenanceCommand):
    command_names = ("import-json",)
    doc_short: ClassVar[str] = "Import legacy TODO.json into the store"
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
        """Import legacy JSON ticket(s) into the store."""
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
    """Register the -s/-t/-tc/-tu/-g display-column flags on *parser*.

    -s -> State, -t/-tc -> create time, -tu -> update time, -g -> Tags.
    Repeatable; the columns render leftmost in the order the flags are given.
    Shared by ls and search so both take the same output selectors (ls is the
    null-query case of search).
    """
    parser.add_argument(
        "-s", dest="columns", const="state", nargs=0, action=_ColumnAction,
        help="show State column (and, without --states, reveal all states incl. done/merged)",
    )
    parser.add_argument(
        "-t", "-tc", dest="columns", const="ctime", nargs=0, action=_ColumnAction,
        help="show create-time column",
    )
    parser.add_argument(
        "-tu", dest="columns", const="utime", nargs=0, action=_ColumnAction,
        help="show update-time column",
    )
    parser.add_argument(
        "-g", dest="columns", const="tags", nargs=0, action=_ColumnAction,
        help="show Tags column (comma-joined)",
    )


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
                e["raw"] for e in tag
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
    summary = summary.get("raw", "") if isinstance(summary, dict) else str(summary or "")
    return {
        "id": full,
        "short": full[:8],
        "summary": summary,
        "state": _column_value(todo, "state"),
        "ctime": _column_value(todo, "ctime"),
        "utime": _column_value(todo, "utime"),
        "tags": _column_value(todo, "tags"),
    }


def _format_rows(rows: Sequence[JsonDict], columns: Sequence[str]) -> List[str]:
    """Render list rows uniformly for ls and search: selected columns leftmost
    (in flag order), then the id, then the summary ALWAYS last.

    Each column is right-padded to the width of its longest value UNDER 30 chars;
    values >= 30 chars are left unpadded and do not widen the column, so a single
    long field (typically the summary) never blows out alignment. Trailing pad on
    the last column is trimmed.
    """
    keys: List[str] = [*columns, "short", "summary"]
    widths: Dict[str, int] = {}
    for key in keys:
        vals = [str(row.get(key, "")) for row in rows]
        widths[key] = max((len(v) for v in vals if len(v) < 30), default=0)
    lines: List[str] = []
    for row in rows:
        fields = [str(row.get(key, "")).ljust(widths[key]) for key in keys]
        lines.append("  ".join(fields).rstrip())
    return lines


def run_search(
    root: Path,
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
        root,
        terms,
        limit=limit,
        embedder_names=embedder_names,
        dry_run=dry_run,
        states=states,
        tags=tags,
    )
    return [todo_row(todo) for todo in result.hits], result.hidden_by_status


class SearchCommand(CorpusQueryCommand):
    command_names = ("search",)
    doc_short: ClassVar[str] = "Vector search todos"
    doc_long: ClassVar[str] = (
        "Search ranks todos by reciprocal-rank fusion over one or more embedders "
        "plus lexical overlap. Multiple text terms are searched google-style (OR): "
        "each term is embedded and matched independently and matching more terms "
        "ranks higher; a doc matching only one term can still appear. A term "
        'is the unit of embedding -- quote a phrase ("bh 791") to match it whole; '
        "unquoted words (bh 791) match individually. A single term that uniquely "
        "prefix-matches one ticket's Id (4+ hex chars, same shape as a selector) "
        "is pinned first regardless of its own lexical/semantic score. Colon "
        "operators (no space before the value) filter by time and are ANDed with "
        "text terms: tc_before:/tc_after: on create_dt, tu_before:/tu_after: on "
        "update_dt, each followed by RFC3339 Z (e.g. tc_after:2026-01-01T00:00:00Z). "
        "Results hide FINAL (done, "
        "merged) by default; pass -s to show all states or --states=<expr> (UPPERCASE "
        "macros ALL, FINAL, PAUSING, WORKING, UNSTARTED, INFO plus lowercase state "
        "names) to filter. --embedder takes a comma list "
        "(default: all non-hidden embedders; see the 'embedders' command). A "
        "requested embedder that is unavailable errors -- pick one explicitly. "
        "Missing vectors are backfilled and stored before ranking unless "
        "--dry-run; a ticket with no vector for an embedder just does not "
        "contribute to that embedder's rank. -s/-t/-tc/-tu/-g add "
        "State/create-time/update-time/Tags columns (leftmost, in flag order, summary "
        "last, columns right-padded to their longest value under 30 chars -- the same "
        "output selectors as ls); results stay in relevance-rank order."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register search arguments."""
        parser.add_argument(
            "query",
            nargs="+",
            metavar="TERM",
            help=(
                "one or more search terms (google-style OR): each text term is "
                "embedded and matched on its own; matching more terms ranks higher. "
                'Quote a phrase ("bh 791") to make it a single term. Time filters: '
                "tc_before:/tc_after:/tu_before:/tu_after:<RFC3339Z> (no space, ANDed)"
            ),
        )
        parser.add_argument("-n", "--limit", type=int, default=20, help="max results")
        parser.add_argument(
            "--embedder",
            help="comma list of embedders (default: all non-hidden, e.g. apple)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="rank against existing vectors only; do not backfill/store any",
        )
        parser.add_argument(
            "--states",
            metavar="EXPR",
            help=(
                "restrict to states: a comma/+/- expression over lowercase state "
                "names and UPPERCASE macros (ALL, FINAL, PAUSING, WORKING, "
                "UNSTARTED, INFO), left-to-right; e.g. WORKING+PAUSING or ALL,-done. "
                "Default hides FINAL (done, merged); pass -s to show all states"
            ),
        )
        parser.add_argument(
            "--tag",
            help="restrict to todos with any of these Tag elements (comma list, "
            "case-insensitive, manual or automatic); e.g. ui,billing",
        )
        _add_column_args(parser)

    def do(self) -> int:
        """Print ranked ticket search hits."""
        root = self.root()
        names: Optional[List[str]] = None
        if self.embedder:
            names = [part.strip() for part in self.embedder.split(",") if part.strip()]
        columns = self.columns or []
        states = resolve_state_filter(self.states, "state" in columns)
        tags = (
            frozenset(part.strip().lower() for part in self.tag.split(",") if part.strip())
            if self.tag
            else None
        )
        rows, hidden_by_status = run_search(
            root,
            self.query,
            limit=self.limit,
            embedder_names=names,
            dry_run=self.dry_run,
            states=states,
            tags=tags,
        )
        for line in _format_rows(rows, columns):
            print(line)
        if hidden_by_status:
            print(f"... {hidden_by_status} hidden by status", file=sys.stderr)
        return 0


class EmbeddersCommand(CorpusQueryCommand):
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


class PromptCommand(CorpusQueryCommand):
    command_names = ("prompt",)
    doc_short: ClassVar[str] = "Print a todo + its parent chain as one startup prompt"
    doc_long: ClassVar[str] = (
        "Prompt concatenates the Summary/Body of a todo and its Parent chain "
        "(context references from set --parent included), farthest ancestors "
        "first and the target last, so a fresh agent with zero context reads WHY "
        "down to WHAT before starting. Read-only: it resolves parents from the db "
        "without checking out branches. Selector is a 4+ hex Id prefix or the "
        "full digest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register prompt arguments."""
        parser.add_argument(
            "selector",
            help="todo selector: Id prefix (4+ hex) or full digest",
        )

    def do(self) -> int:
        """Print the parent-chain startup prompt for the selected todo."""
        root = self.root()
        print(build_prompt_chain(root, self.selector))
        return 0


class LsCommand(CorpusQueryCommand):
    command_names = ("ls",)
    doc_short: ClassVar[str] = "List known todo ids and summaries"
    doc_long: ClassVar[str] = (
        "Ls prints one line per todo known to the resolved todo directory, as '<id[0:8]>  "
        "<summary>'. Where-to-find-it only; use 'read <id>' for full todo content. By default it "
        "hides terminated states (done, merged) via the config.json default filter (ALL,-FINAL); "
        "pass -s to show all states, or --states=<expr> to filter explicitly (UPPERCASE macros "
        "ALL, FINAL, PAUSING, WORKING, UNSTARTED, INFO plus lowercase state names, e.g. "
        "WORKING+PAUSING or ALL,-done). -s adds a State column, -t/-tc a create-time column, -tu "
        "an update-time column, -g a Tags column; selected columns print leftmost in the order "
        "the flags are given, summary always last, and each column is right-padded to its longest "
        "value under 30 chars. With any column flag the rows sort ascending by the leftmost "
        "selected column (oldest first for times); otherwise insertion order. ls and search take "
        "the same output selectors (ls is the null-query case of search)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register ls arguments."""
        parser.add_argument(
            "--states",
            metavar="EXPR",
            help=(
                "restrict to states: a comma/+/- expression over lowercase state "
                "names and UPPERCASE macros (ALL, FINAL, PAUSING, WORKING, "
                "UNSTARTED, INFO); default hides FINAL (done, merged); -s shows all"
            ),
        )
        _add_column_args(parser)

    def do(self) -> int:
        """Print '<cols>  <id>  <summary>' for todos matching the state filter.

        Hides terminated (FINAL) states by default; -s reveals all, --states
        filters explicitly (see resolve_state_filter).
        """
        if not use_store():
            raise TodoError("ls requires the db store (unset TODO_USE_JSON)")
        columns = self.columns or []
        # get_store() resolves the todo dir, which default_state_filter reads.
        todos = [normalize_todo_schema(t) for t in todo_store.get_store().list_all()]
        allowed = resolve_state_filter(self.states, "state" in columns)
        rows = [
            todo_row(todo)
            for todo in todos
            if (current_state_name(todo) or "") in allowed
        ]
        if columns:
            rows.sort(key=lambda row: str(row.get(columns[0], "")))
        for line in _format_rows(rows, columns):
            print(line)
        return 0


class BaseDirCommand(EnvironmentCommand):
    command_names = ("basedir",)
    doc_short: ClassVar[str] = "Print the todo base directory"
    doc_long: ClassVar[str] = (
        "Basedir prints the resolved todo base directory for this invocation -- where "
        "config.json, the ticket store (json files or sqlite.db), and worktrees live. "
        "Resolution order: $TODO_DIR, then .todo at each level from "
        "<main-checkout-root> up to and including $HOME (the walk stops at $HOME), "
        "then $HOME/.todo. The repo anchor is the repo's MAIN checkout root, not the "
        "current worktree, so all worktrees of a repo share one store."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Basedir takes no arguments."""

    def do(self) -> int:
        """Print the resolved todo base directory."""
        print(todo_db.todo_dir())
        return 0


class RepoDirCommand(EnvironmentCommand):
    command_names = ("repodir",)
    doc_short: ClassVar[str] = "Print the repo directory a todo lives in"
    doc_long: ClassVar[str] = (
        "Repodir prints the concrete repo directory for the selected todo on this machine: "
        "the repo's MAIN checkout root (not the current worktree). Absolute paths are never "
        "stored -- the todo's repo name only identifies the repo (and warns if the CWD is a "
        "different one). Selector is a 4+ hex Id prefix or the full digest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register repodir arguments."""
        parser.add_argument(
            "selector",
            help="todo selector: Id prefix (4+ hex) or full digest",
        )

    def do(self) -> int:
        """Print the repo's main checkout root for the selected todo."""
        root = self.root()
        resolve_ticket_by_id(root, self.selector)  # validates id; warns on repo mismatch
        print(todo_db.main_checkout_root() or root)
        return 0


class ExportToFileCommand(StoreMaintenanceCommand):
    command_names = ("export-to-file",)
    doc_short: ClassVar[str] = "Export todos to <basedir>/storage/<id>.json"
    doc_long: ClassVar[str] = (
        "Export-to-file writes each selected todo as a round-trippable '<id>.json' "
        "(the same object shape import-json reads) into <basedir>/storage/. --basedir "
        "defaults to the resolved todo base directory. Give one or more 4+ hex Id "
        "prefixes, or the meta id ALL to export every todo in the store. With --remove, "
        "each todo is removed from the store after its file is written: --remove=hard "
        "permanently deletes it (embeddings cascade away); --remove or --remove=soft "
        "(default) keeps a recoverable tombstone -- a deleted_tickets row in the sqlite "
        "store, or an '<id>.deleted' file in a json-dir store. There is no recovery "
        "command yet; restore by hand if needed."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register export-to-file arguments."""
        parser.add_argument(
            "ids", nargs="+", help="4+ hex Id prefixes, or the meta id ALL for every todo"
        )
        parser.add_argument(
            "--basedir",
            help="base dir for output (default: todo basedir); files go to <basedir>/storage/",
        )
        parser.add_argument(
            "--remove",
            nargs="?",
            const="soft",
            choices=("soft", "hard"),
            default=None,
            help="remove each todo from the store after export: soft (default) tombstones, hard deletes",
        )

    @staticmethod
    def _resolve(store: "todo_store.TodoStore", selector: str) -> JsonDict:
        """Resolve one id-prefix selector to a single todo in *store*."""
        todos = [match[2] for match in store.find_by_id_prefix(selector)]
        if not todos:
            raise TodoError(f"no todo matches {selector!r}")
        if len(todos) > 1:
            shorts = ", ".join(sorted({str(t.get("Id", ""))[:8] for t in todos}))
            raise TodoError(f"ambiguous selector {selector!r}: {shorts}")
        return todos[0]

    def do(self) -> int:
        """Export selected todos to files, optionally removing them from the store."""
        store = todo_store.get_store()
        base = Path(self.basedir) if self.basedir else todo_db.todo_dir()
        out_dir = base / "storage"
        out_dir.mkdir(parents=True, exist_ok=True)

        if any(sel == "ALL" for sel in self.ids):
            todos = store.list_all()
        else:
            todos = [self._resolve(store, sel) for sel in self.ids]

        exported = 0
        for todo in todos:
            tid = str(todo.get("Id") or "")
            if not tid:
                raise TodoError("todo missing Id; cannot export")
            path = out_dir / f"{tid}.json"
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(todo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(path)
            note = ""
            if self.remove is not None:
                removed = store.delete(todo, hard=(self.remove == "hard"))
                note = f"  (removed: {self.remove})" if removed else "  (not in store)"
            print(f"{tid[:8]}  {path}{note}")
            exported += 1
        print(f"exported {exported} todo(s) to {out_dir}")
        return 0


class MigrateToLatestCommand(StoreMaintenanceCommand):
    command_names = ("migrate-to-latest",)
    doc_short: ClassVar[str] = "Sweep the store's records to the latest schema"
    doc_long: ClassVar[str] = (
        "Migrate-to-latest sweeps every record in the resolved store, running "
        "todo_db.migrate_record on each to fold in every pending RECORD_MIGRATIONS "
        "step (renames, shape changes) and stamp _schema, then advances the "
        "store's data_version marker to todo_db.SCHEMA_VERSION. Table-level "
        "migrations (sqlite) apply automatically as a side effect of the sweep. "
        "--dry-run reports the scanned/would-migrate counts without writing "
        "anything (no put, no data_version bump)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register migrate-to-latest arguments."""
        parser.add_argument(
            "--dry-run", action="store_true", help="report counts without writing"
        )

    def do(self) -> int:
        """Sweep the resolved store to the latest schema and print a summary."""
        report = migrate_store(todo_store.get_store(), dry_run=self.dry_run)
        print(json.dumps(report, indent=2))
        return 0


# Derived from the class tree, not hand-kept: a command joins the CLI by
# choosing a group to subclass, and cannot be registered any other way. The
# previous 37-entry tuple was a second list to remember.
COMMAND_CLASSES: Sequence[type[TodoSubCommand]] = tuple(
    leaf for group in COMMAND_GROUPS for leaf in _command_leaves(group)
)


def grouped_command_listing() -> str:
    """The --help command list, under one heading per top-level group.

    argparse has no notion of subcommand groups, so the listing is built here
    and carried in the epilog (already raw-formatted); the flat blob argparse
    would print is suppressed in register(). Width is fixed rather than
    computed: the columns should not shift because one long command name was
    added somewhere else in the tree.
    """
    lines: List[str] = []
    for group in COMMAND_GROUPS:
        lines.append(f"{group.group_title}:")
        for leaf in _command_leaves(group):
            for name in leaf.command_names:
                lines.append(f"  {name:<18} {leaf.doc_short}")
        lines.append("")
    return "\n".join(lines)


TOP_LEVEL_EPILOG = """\
Repo & todo identity:
  gitroot      `git rev-parse --show-toplevel`: the CURRENT working tree (a
               linked worktree when in one). Used for git operations.
  main checkout root
               the repo's PRIMARY working tree (first `git worktree list` entry).
               The STORAGE anchor: the todo store lives at <it>/.todo/, so all
               worktrees of a repo share one store. Git ops still use gitroot.
  TODO branch  a git repo branch that carries a todo in sqlite.
  todo dir     resolved once per invocation: $TODO_DIR, else .todo walked from
               <main-checkout-root> up to and including ~ (stops at ~), else
               ~/.todo (first with sqlite.db wins; same dir for db and worktrees).
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
            "hard-errors if CWD is not a git repo.\n\n"
            # In the description, not the epilog: argparse would print the
            # commands below an empty "positional arguments: COMMAND" block,
            # and the commands are what --help is for.
            + grouped_command_listing()
        ),
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub: argparse._SubParsersAction = parser.add_subparsers(
        dest="command",
        required=True,
        # Collapses the 37-choice blob in the usage line; the epilog lists them.
        metavar="COMMAND",
    )

    for command_cls in COMMAND_CLASSES:
        command_cls.register(sub)

    return parser


LOG_DIR: Path = Path("/usr/local/var/log/todo")
LOG_FILE: Path = LOG_DIR / "todo.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5

# Environment variables an AI coding agent / automation harness exports into the
# processes it spawns. Presence of any of these is strong evidence the caller is
# not a human at an interactive shell. Prefix-matched, so the whole CLAUDE* /
# CURSOR* / AIDER* families are covered -- including CLAUDE_EFFORT and every
# CLAUDE_*SESSION* var. Deliberately broad: we capture their values now and can
# prune the set later once we see what is actually useful.
_AGENT_ENV_MARKERS: tuple[str, ...] = (
    "CLAUDECODE",
    "CLAUDE_",
    "AI_AGENT",
    "CURSOR_",
    "AIDER_",
)
# Parent-process command names that mean an agent spawned us directly.
_AGENT_PARENT_TOKENS: tuple[str, ...] = ("claude", "cursor")

# Env var NAME fragments whose VALUES must never hit the log. Matched on the name
# only (case-insensitive substring) -- we deliberately do NOT inspect values. A
# matching var is still recorded with its value replaced by "<redacted>", so the
# fact that it was set stays auditable without leaking the secret. Edit this list
# to blacklist more names.
_REDACT_ENV_NAME_FRAGMENTS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "APIKEY",
    "API_KEY",
    "KEY",
    "AUTH",
)

_INVOCATION_LOGGER: Optional[logging.Logger] = None


def _redacted_env_value(name: str, value: str) -> str:
    """Value for *name*, or '<redacted>' when the NAME matches the blacklist.

    Name-based only by design: values are never scanned.
    """
    upper: str = name.upper()
    if any(fragment in upper for fragment in _REDACT_ENV_NAME_FRAGMENTS):
        return "<redacted>"
    return value


def _parent_comm() -> str:
    """Command name of the parent process (basename; '' if undeterminable)."""
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(os.getppid())],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return os.path.basename(result.stdout.strip())


def detect_caller() -> "tuple[str, JsonDict]":
    """Classify the invoker as 'user', 'agent', or 'unknown', with evidence.

    Authority order: agent env markers or an agent parent process -> 'agent';
    else an interactive stdin tty -> 'user'; else 'unknown' (a non-interactive
    pipe with no agent marker, e.g. a shell script or cron job). The raw signals
    are returned alongside so the log stays auditable and the heuristic can be
    refined later without re-deriving them.
    """
    # Capture the matched marker vars with their VALUES (name -> value), not just
    # names: session ids, entrypoint, effort, execpath, etc. are all correlation-
    # worthy. Broad on purpose; prune later.
    agent_env: JsonDict = {
        name: _redacted_env_value(name, value)
        for name, value in os.environ.items()
        if any(name.startswith(marker) or name == marker for marker in _AGENT_ENV_MARKERS)
    }
    parent: str = _parent_comm()
    agent_parent: bool = any(tok in parent.lower() for tok in _AGENT_PARENT_TOKENS)
    try:
        tty: bool = sys.stdin.isatty()
    except (ValueError, OSError):
        tty = False
    # agent_env now carries full name->value pairs (see above). `session` is the
    # primary correlation key promoted to the top for easy grep; it is also
    # present inside agent_env.
    signals: JsonDict = {
        "tty": tty,
        "parent": parent,
        "session": os.environ.get("CLAUDE_CODE_SESSION_ID") or "",
        "term": os.environ.get("TERM_PROGRAM") or "",
        "term_version": os.environ.get("TERM_PROGRAM_VERSION") or "",
        "agent_env": agent_env,
    }
    if agent_env or agent_parent:
        caller: str = "agent"
    elif tty:
        caller = "user"
    else:
        caller = "unknown"
    return caller, signals


def _invocation_logger() -> Optional[logging.Logger]:
    """Singleton rotating-file logger for invocation records, or None.

    Best-effort: if the log directory or file cannot be opened, returns None so
    that auditing never causes a todo command to fail.
    """
    global _INVOCATION_LOGGER  # noqa: PLW0603 - process-lifetime singleton
    if _INVOCATION_LOGGER is not None:
        return _INVOCATION_LOGGER
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger: logging.Logger = logging.getLogger("todo.invocation")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers = [handler]
    _INVOCATION_LOGGER = logger
    return logger


def log_invocation(command: str, argv: Sequence[str], exit_code: int, dur_ms: int) -> None:
    """Append one JSON-lines record for this invocation. Never raises."""
    logger: Optional[logging.Logger] = _invocation_logger()
    if logger is None:
        return
    caller, signals = detect_caller()
    try:
        cwd: str = os.getcwd()
    except OSError:
        cwd = ""
    record: JsonDict = {
        "ts": utc_now(),
        "pid": os.getpid(),
        "user": os.environ.get("USER") or "",
        "caller": caller,
        "cmd": command,
        "argv": list(argv),
        "cwd": cwd,
        "exit": exit_code,
        "dur_ms": dur_ms,
        "signals": signals,
    }
    try:
        logger.info(json.dumps(record, separators=(",", ":")))
    except (OSError, ValueError, TypeError):
        pass


def _detect_agent_framework() -> Optional[str]:
    """Best-effort name of the agent framework driving this invocation, from env.

    Env vars are inherited by the spawned process, so they identify the *caller*
    right now (a config file like CLAUDE.md/AGENTS.md only says what is
    configured, not who is running). Cascade: the emerging cross-vendor
    ``AGENT=<name>`` convention first, then per-tool signals. Returns a lowercase
    framework name, or ``None`` for a plain shell / unknown caller (skills-doctor
    stays silent then).
    """
    agent: str = os.environ.get("AGENT", "").strip().lower()
    if agent:
        return agent
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_CLI"):
        return "cursor"
    if os.environ.get("OPENCODE_RUN_ID"):
        return "opencode"
    return None


def _buried_claude_skills() -> List[str]:
    """Complaints for skills installed too deep for Claude Code to discover.

    Claude Code scans ``<root>/<name>/SKILL.md`` exactly one level under each
    skills root (``~/.claude/skills`` and a project ``.claude/skills``). A skill
    whose ``SKILL.md`` sits deeper (``<root>/<group>/<sub>/SKILL.md``) is
    invisible -- UNLESS a top-level ``<sub>`` entry separately exposes it (e.g. a
    sibling symlink), which is not flagged. Cheap: one listdir per root plus a
    shallow peek into the non-skill dirs.
    """
    complaints: List[str] = []
    roots: List[Path] = [Path.home() / ".claude" / "skills"]
    project_root: Path = Path.cwd() / ".claude" / "skills"
    if project_root.is_dir():
        roots.append(project_root)
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries: List[Path] = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            continue
        discoverable = {p.name for p in entries if (p / "SKILL.md").is_file()}
        for entry in entries:
            if (entry / "SKILL.md").is_file():
                continue
            try:
                nested = sorted(
                    sub.name
                    for sub in entry.iterdir()
                    if sub.is_dir() and (sub / "SKILL.md").is_file()
                )
            except OSError:
                nested = []
            for sub in nested:
                if sub in discoverable:
                    continue
                complaints.append(
                    f"skill '{sub}' is buried at {entry.name}/{sub}/ under {root} "
                    f"(Claude Code scans one level deep); symlink it to {root}/{sub}"
                )
    return complaints


def _warn_if_skills_buried() -> None:
    """Complain on stderr, once per session, when the calling agent framework
    cannot discover skills installed too deep for its scanner.

    The INVERSE of ``_warn_if_store_behind``: that nudge targets a human at a tty;
    this one targets an AGENT driving non-interactively (its stderr is a pipe the
    agent reads back), so it is gated on *framework detection*, NOT ``isatty``, and
    stays silent for a plain shell or unknown caller. Frameworks whose discovery
    rules skills-doctor does not yet know emit a FIXME asking for them. Cheap and
    non-fatal -- a health nudge must never break the tool.
    """
    try:
        framework: Optional[str] = _detect_agent_framework()
        if framework is None:
            return
        # Complain at most once per session (agents call todo.py many times),
        # keyed on whatever session id the detected framework exposes.
        session: str = (
            os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or os.environ.get("CURSOR_TRACE_ID")
            or ""
        )
        marker: Path = Path(tempfile.gettempdir()) / f".todo-skills-doctor.{framework}.{session}"
        if session and marker.exists():
            return
        if framework == "claude":
            for complaint in _buried_claude_skills():
                print(f"todo.py: skills-doctor: {complaint}", file=sys.stderr)
        elif framework == "cursor":
            # FIXME: cursor -- discovery root + scan depth not yet known.
            print(
                "todo.py: skills-doctor: FIXME: cursor, how do you like your SKILLs "
                "in the morning? (teach skills-doctor your discovery root + scan depth)",
                file=sys.stderr,
            )
        elif framework in ("codex", "chatgpt", "openai"):
            # FIXME: chatgpt/codex -- discovery root + scan depth not yet known.
            print(
                "todo.py: skills-doctor: FIXME: chatgpt/codex, where do you read SKILLs "
                "from? (teach skills-doctor your discovery root + scan depth)",
                file=sys.stderr,
            )
        else:
            print(
                f"todo.py: skills-doctor: FIXME: {framework}, skill-discovery rules "
                "not yet known; teach skills-doctor this framework",
                file=sys.stderr,
            )
        if session:
            try:
                marker.touch()
            except OSError:
                pass
    except Exception:  # pylint: disable=broad-except
        # A startup health nudge must never break the tool.
        return


def _warn_if_store_behind() -> None:
    """Print a one-line stderr warning when the store's records lag SCHEMA_VERSION.

    Cheap (one get_data_version() call), non-fatal (never raises, never blocks,
    never auto-migrates -- `doctor` sweeps opportunistically, so point there).
    Restricted to interactive terminals: automation (agents, scripts, tests)
    drives todo.py non-interactively and expects quiet, deterministic stderr, so
    this nudge is for a human at a real terminal only.
    """
    if not sys.stderr.isatty():
        return
    try:
        current = todo_store.get_store().get_data_version()
    except (todo_store.TodoStoreError, OSError):
        return
    if current < todo_db.SCHEMA_VERSION:
        print(
            f"todo.py: warning: store data_version {current} is behind schema "
            f"{todo_db.SCHEMA_VERSION}; run 'todo.py doctor ALL' to sweep records",
            file=sys.stderr,
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)
    logged_argv: List[str] = list(argv) if argv is not None else sys.argv[1:]
    command_name: str = getattr(args, "command", "") or ""
    start: float = time.monotonic()
    exit_code: int = 1
    try:
        _warn_if_store_behind()
        _warn_if_skills_buried()
        command: TodoSubCommand = args.command_cls(args)
        exit_code = int(command.do())
        return exit_code
    except todo_store.LockTimeout as exc:
        # EX_TEMPFAIL: transient per-TODO lock contention. The caller should
        # retry rather than treat this as a hard failure.
        print(f"todo.py: ERETRY: {exc}", file=sys.stderr)
        exit_code = 75
        return 75
    except todo_store.TodoStoreError as exc:
        print(f"todo.py: {exc}", file=sys.stderr)
        exit_code = 1
        return 1
    except TodoError as exc:
        print(f"todo.py: {exc}", file=sys.stderr)
        exit_code = 1
        return 1
    finally:
        log_invocation(command_name, logged_argv, exit_code, int((time.monotonic() - start) * 1000))


if __name__ == "__main__":
    raise SystemExit(main())

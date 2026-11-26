"""Local core of the todo CLI: the mechanism behind todo.py's subcommands.

Work-item, note, relto, subtodo, state, tag and worktree operations, the JSON
path primitives, PR reconciliation and the store-file autocommit mechanics. No
argparse, no stdout, no ``sys.exit``; failures raise ``TodoError``. Calls only
the common core (``todo_common`` and the library modules).
"""

# pylint: disable=too-many-lines

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

import git_command
import todo_db
import todo_objid
import todo_ref
import todo_store
import todo_embed
from todo_common import (
    JsonDict,
    TodoError,
    _EMBED_FIELDS,
    _raw_of,
    branch_exists,
    commit_todo,
    current_branch,
    current_state_name,
    git_url_for_repo,
    head_sha,
    repo_key,
    resolve_ticket_by_id,
    run_git,
    use_store,
    utc_now,
    write_todo_worktree,
)

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


STOPWORDS = frozenset(
    {"a", "an", "the", "to", "from", "for", "and", "or", "in", "on", "of"}
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


def kebab_branch_name(ticket_id: str, summary: str) -> str:
    """Build Branch label from id prefix and summary words."""
    words: List[str] = re.sub(r"[^a-zA-Z0-9\s]", " ", summary.lower()).split()
    slug_words: List[str] = [word for word in words if word not in STOPWORDS][:4]
    slug: str = "-".join(slug_words) if slug_words else "ticket"
    branch: str = f"{ticket_id[:8]}-{slug}"
    return branch[:32]


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


# pylint: disable-next=too-many-arguments
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
    return (
        branch
        or str(ticket.get("Branch") or "")
        or kebab_branch_name(ticket_id, _raw_of(ticket, "Summary") or "")
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


# pylint: disable-next=too-many-arguments,too-many-locals
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
        set_state(
            todo,
            state,
            note=note,
            last_commit=last_commit,
            merged_into=merged_into,
            owner=owner,
            pr=pr,
            merge_commit=merge_commit,
        )
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
    seen = {
        e["raw"]
        for e in elements
        if isinstance(e, dict) and isinstance(e.get("raw"), str)
    }
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
    targets = {
        tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()
    }
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
        else [
            e
            for e in elements
            if not (isinstance(e, dict) and e.get("manual") is False)
        ]
    )
    if kept:
        todo["Tag"] = kept
    else:
        todo.pop("Tag", None)
    return len(elements) - len(kept)


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


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-positional-arguments
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
# A WorkItem is either not-done freetext (kind "task") or one of six typed
# done kinds. ONE COMMAND PER KIND, always: the command performs the work and
# the kind is the receipt it writes down, which is why a kind is never a
# `--status` a caller can assert without doing the thing it claims. What each
# receipt carries is what its command can actually witness:
#   - "code"          local coding; carries a `sha` (invariant #1)
#                     [work-item-done; needs the branch checked out, and makes
#                     the commit itself when the tree is dirty]
#   - "merge_subtodo" a merged subtodo; carries `subtodo_id` and a `sha`
#                     [merge-subtodo, after YOUR git merge]
#   - "start_subtodo" a fired subtodo; carries `subtodo_id`, no sha
#                     [add-subtodo, which creates the child branch]
#   - "checkpoint"    the step FINISHED but produced no commit (recon, waits,
#                     bookkeeping); carries `at_sha` -- observational (where
#                     HEAD stood), never attribution -- and a `message` saying
#                     what the no-code step did. [work-item-checkpoint; needs
#                     the branch checked out to read HEAD, and a clean tree so
#                     no real work is stranded]
#   - "blocked"       the step is still OWED but cannot be done AS WRITTEN (the
#                     approach turned out to be impossible, or the data it needs
#                     does not exist). Carries the long-form `message`: what was
#                     tried, what was found, what the options are. No sha of
#                     either sort -- nothing was produced and nothing observed.
#                     [work-item-blocked, store-only]
#   - "obsolete"      the step is no longer WANTED: descoped, superseded, or
#                     subsumed by another step. Carries a `message` saying why.
#                     No sha of either sort. Nobody owes an obsolete step
#                     anything, which is the whole difference from `blocked`.
#                     [work-item-obsolete, store-only]
# The last three close an item without a commit and share one mechanism
# (close_workitem): patch the node, then slot it at the end of the done prefix.
# Only their MEANING differs, and that is what having three names buys. Each
# kind still keeps only its own metadata, mirroring the State-value doctrine:
# inapplicable metadata raises instead of being silently dropped.
# Deleting a step is none of the above -- it erases that the step was ever
# planned, so it is for a plan that was never right, not one that changed.
# The cursor is the first not-done item (derived). Working proceeds by marking
# the cursor done and advancing; the index never decreases though the list may
# grow (invariant #3). A todo is done when nothing is not-done (invariant #7).

WORKITEM_TASK = "task"


WORKITEM_CODE = "code"


WORKITEM_MERGE_SUBTODO = "merge_subtodo"


WORKITEM_START_SUBTODO = "start_subtodo"


WORKITEM_CHECKPOINT = "checkpoint"


WORKITEM_BLOCKED = "blocked"


WORKITEM_OBSOLETE = "obsolete"


# The three that close an item with no commit: same mechanism, different
# claim. Every one of them requires its reason to be recorded.
WORKITEM_NOCOMMIT_KINDS = (WORKITEM_CHECKPOINT, WORKITEM_BLOCKED, WORKITEM_OBSOLETE)


# git's null object id: an EXPLICIT no-change sentinel on a done code/merge
# item's `sha`. LEGACY ENCODING, no live producer. It was how `work-item-done
# --blocked` recorded "no commit, and none is coming" -- a `code` item that was
# not code, so every reader needed a special case for it. kind="blocked" says
# the same thing in the field that is supposed to say it, and the sentinel is
# left only for records already carrying it: old blocked items, and the
# retrofit for records that misattribute a foreign commit. It is deliberately
# NOT migrated to kind=blocked, because those two producers are
# indistinguishable after the fact and guessing would relabel a bad
# attribution as a decision nobody made. Readers must never resolve it,
# attribute it, or report it as a branch commit; doctor accepts it mid-list and
# rejects it as the last item.
WORKITEM_NULL_SHA = "0" * 40


# "Done" here means CLOSED -- the cursor is past it and the plan owes it
# nothing further. An obsolete item is closed without ever having been done,
# which is why the flag on the node stays `done: true`: every reader that walks
# the plan (cursor, is-done, #3's prefix rule) asks "is this still open?", and
# the answer for a dropped step is no.
WORKITEM_DONE_KINDS = frozenset(
    {
        WORKITEM_CODE,
        WORKITEM_MERGE_SUBTODO,
        WORKITEM_START_SUBTODO,
        *WORKITEM_NOCOMMIT_KINDS,
    }
)


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


# --- WorkItem addressing ---------------------------------------------------
#
# A work-item command names ONE item, three ways:
#
#   (omitted)      the cursor -- the first not-done item; the working default,
#                  which is what the one-item-at-a-time loop wants
#   <int>          a 0-based index into WorkItems; a negative one counts from
#                  the end the way python's own indexing does, so -1 is the
#                  last item and -2 the one before it
#   objid:<hex>    the item carrying that objid -- the same stable handle
#                  permalinks are built on. An objid is an allocation number
#                  rendered %04x, so leading zeros are optional on input:
#                  objid:3 == objid:03 == objid:0003
#
# Indexes read straight off `work-item-read`, `doctor` findings, and permalinks
# (all 0-based), which makes them easy to type and unsafe to keep: an insert,
# a delete, or a reorder renumbers everything after it. An objid never moves,
# so a plan edit worked out in advance -- a topological pass over a plan whose
# steps came out in the wrong dependency order, say -- addresses by objid.
#
# A bare hex string is an INDEX, never an id: `12` means index 12, not objid
# 0012. That is the permalink grammar's rule too (a bare segment is always an
# index), and it is why an objid has to name its scheme.
#
# The 4-character floor permalinks put on a prefix (``todo_url.MIN_PREFIX``)
# does NOT apply here, and neither does its refusal to pad. There, a prefix is
# matched against every object in the record, so a short one is a coin flip;
# here the short form is padded to a whole id first (an id is a number, and
# 0003 is how 3 is written) and then matched against one short list, where it
# is either unique or reported as ambiguous.

WORKITEM_OBJID_SCHEME: str = "objid:"


def _index_by_objid(items: Sequence[Any], prefix: str, *, noun: str) -> int:
    """Return the index of the one *noun* in *items* whose objid matches *prefix*.

    *prefix* is zero-padded to a whole id first, so `3` finds `0003`; a value
    already that long acts as a plain prefix. See the section comment above.
    *noun* names what is being addressed ("work item", "note", ...) so the
    error wording stays specific to the kind of thing a caller misaddressed.
    """
    if not prefix:
        raise TodoError(
            f"{WORKITEM_OBJID_SCHEME} needs a value, e.g. {WORKITEM_OBJID_SCHEME}0a3f"
        )
    if not todo_objid.is_objid_prefix(prefix):
        raise TodoError(
            f"objid {prefix!r} is not lowercase hex; an objid has exactly one spelling"
        )
    padded = todo_objid.normalize_objid_prefix(prefix)
    hits = [
        index
        for index, item in enumerate(items)
        if isinstance(item, dict)
        and isinstance(item.get(todo_objid.OBJID_KEY), str)
        and item[todo_objid.OBJID_KEY].startswith(padded)
    ]
    if not hits:
        raise TodoError(
            f"no {noun} in this todo carries objid {padded!r}"
            + (f" (from {prefix!r})" if padded != prefix else "")
        )
    if len(hits) > 1:
        joined = ", ".join(str(index) for index in hits)
        raise TodoError(
            f"objid {padded!r} is ambiguous: matches {noun}s {joined}; "
            "use the whole id"
        )
    return hits[0]


def _workitem_index_by_objid(items: Sequence[Any], prefix: str) -> int:
    """Return the index of the one work item whose objid matches *prefix*."""
    return _index_by_objid(items, prefix, noun="work item")


def _index_by_number(items: Sequence[Any], address: str, *, noun: str) -> int:
    """Return the index *address* names, resolving a negative one from the end.

    *noun* names what is being addressed, for error wording specific to it.
    """
    try:
        index = int(address, 10)
    except ValueError:
        raise TodoError(
            f"{address!r} addresses nothing: pass an index (negative counts from the "
            f"end) or {WORKITEM_OBJID_SCHEME}<hex>"
        ) from None
    if not items:
        raise TodoError(f"this todo has no {noun}s")
    resolved = index + len(items) if index < 0 else index
    if not 0 <= resolved < len(items):
        raise TodoError(
            f"{noun} {index} is out of range; this todo has {len(items)} "
            f"(0..{len(items) - 1}, or -1..-{len(items)} from the end)"
        )
    return resolved


def _workitem_index_by_number(items: Sequence[Any], address: str) -> int:
    """Return the index *address* names, resolving a negative one from the end."""
    return _index_by_number(items, address, noun="work item")


def resolve_workitem_index(todo: JsonDict, address: Optional[str], *, what: str) -> int:
    """Return the WorkItems index *address* names, or the cursor's when it is None.

    *what* is the verb for the no-open-item message ("replace", "delete"), which
    only an omitted address can produce. Raises TodoError naming what failed --
    no open item, a non-address, an out-of-range index, an unknown or ambiguous
    objid -- so no caller has to re-check the result.
    """
    items: Sequence[Any] = todo.get("WorkItems") or []
    if address is None:
        index = cursor_index(todo)
        if index is None:
            raise TodoError(f"no open work item to {what}")
        return index
    if address.startswith(WORKITEM_OBJID_SCHEME):
        return _workitem_index_by_objid(items, address[len(WORKITEM_OBJID_SCHEME) :])
    return _workitem_index_by_number(items, address)


def resolve_note_index(todo: JsonDict, address: str) -> int:
    """Return the Notes index *address* names.

    Same addressing grammar as a work item -- an index (negative counts from
    the end) or objid:<hex> -- but there is no cursor default: a note has no
    status, so an omitted target means "every note", which the caller (not
    this function) handles before *address* is required.
    """
    items: Sequence[Any] = todo.get("Notes") or []
    if address.startswith(WORKITEM_OBJID_SCHEME):
        return _index_by_objid(
            items, address[len(WORKITEM_OBJID_SCHEME) :], noun="note"
        )
    return _index_by_number(items, address, noun="note")


def resolve_relto_host(todo: JsonDict, host: str) -> str:
    """Return the json dot-path *host* names among the three legal relto hosts.

    Four spellings collapse onto the three hosts ``_RELTO_HOST_RE`` encodes
    (see ``relto_findings``): the literal ``body`` for the ``Body`` field;
    ``objid:<hex>`` (4+ hex, record-wide), resolved with ``todo_ref.resolve_local``
    exactly as a permalink resolves ``objid:<hex>`` and then checked against
    ``_RELTO_HOST_RE`` -- an objid landing on a Tag, a Subtodos entry, or a
    relto element itself is refused, naming what it hit; and
    ``note:<index>`` / ``workitem:<index>`` (0-based, negative counting from
    the end), reusing ``_index_by_number`` against the Notes / WorkItems list
    the way work-item and note addressing already do.
    """
    if host == "body":
        return "Body"
    if host.startswith(todo_ref.OBJID_SCHEME):
        try:
            path = todo_ref.resolve_local(todo, host)
        except todo_ref.TodoRefError as exc:
            raise TodoError(str(exc)) from exc
        if not _RELTO_HOST_RE.match(path):
            raise TodoError(
                f"{host} resolves to {path}, which is not a legal relto host; relto is "
                "legal only on Body, a Notes element, or a WorkItems element"
            )
        return path
    if host.startswith("note:"):
        items: Sequence[Any] = todo.get("Notes") or []
        index = _index_by_number(items, host[len("note:") :], noun="note")
        return f"Notes.{index}"
    if host.startswith("workitem:"):
        items = todo.get("WorkItems") or []
        index = _index_by_number(items, host[len("workitem:") :], noun="work item")
        return f"WorkItems.{index}"
    raise TodoError(
        f"unrecognized relto host {host!r}; expected body, {todo_ref.OBJID_SCHEME}<hex>, "
        "note:<index>, or workitem:<index>"
    )


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
            "note": "run doctor first (must be ok); "
            "synthesize ActualSummary from the done WorkItems",
        }
    item = todo["WorkItems"][index]
    execution = item.get("execution") if isinstance(item, dict) else None
    execution = execution if isinstance(execution, dict) else {}
    primitive = execution.get("primitive")
    wait_for = [w[:8] for w in (execution.get("wait_for") or []) if isinstance(w, str)]
    subtodo_id = execution.get("subtodo_id")
    child = (
        subtodo_id[:8] if isinstance(subtodo_id, str) and subtodo_id else "<child-id>"
    )
    ids = " ".join(wait_for) or "<child-id>..."
    if primitive == "add-subtodo":
        return {
            "action": "add-subtodo",
            "command": f"todo.py add-subtodo {self_id} --summary=...",
        }
    if primitive in (WORKITEM_MERGE_SUBTODO, "merge-subtodo"):
        return {"action": "merge-subtodo", "command": f"todo.py merge-subtodo {child}"}
    if primitive == "wait-and-merge" or (
        wait_for and execution.get("mode") == "barrier"
    ):
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
    self-describing (what actually changed -- e.g. tests added) without resolving shas.
    """
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
    item's high-level description unless *done_item* already set one, and so does
    its objid. Returns the affected index."""
    items = list(todo.get("WorkItems") or [])
    index = cursor_index(todo)
    if index is None:
        items.append(done_item)
        index = len(items) - 1
    else:
        if not done_item.get("summary"):
            done_item["summary"] = items[index].get("summary", "")
        # Completing a step does not make it a different step. The objid is the
        # item's identity, so it carries over and a permalink minted while the
        # step was still open goes on resolving to it -- dropping it would mint
        # a fresh id at the next write, and silently, since stamping only fills
        # gaps.
        objid = items[index].get(todo_objid.OBJID_KEY)
        if todo_objid.is_objid(objid):
            done_item[todo_objid.OBJID_KEY] = objid
        items[index] = done_item
    todo["WorkItems"] = items
    return index


# pylint: disable-next=too-many-arguments
def close_workitem(
    todo: JsonDict,
    index: int,
    kind: str,
    *,
    message: str,
    summary: str = "",
    extra: Optional[JsonDict] = None,
) -> int:
    """Close the not-done item at *index* as done *kind*; return where it landed.

    The one mechanism behind checkpoint, blocked and obsolete -- the three
    receipts that close an item without a commit. Two moves:

    PATCH, never rebuild. The step is not being swapped for a different one, so
    the node keeps its objid (every permalink already handed out for it stays
    valid) along with anything else the plan attached to it. *extra* adds the
    kind's own metadata; *summary* overrides the step's description only when
    given, since patching already keeps it.

    SLOT it at the end of the done prefix. A closed step belongs to the history
    rather than the remaining plan, and without the move a step closed further
    down the list would leave a done item sitting behind not-done ones, which
    is exactly what invariant #3 forbids.

    Caller must have checked that *index* names a not-done item
    (``require_open_workitem``), which is also what makes the cursor lookup
    here safe."""
    frontier = resolve_workitem_index(todo, None, what=f"close as {kind}")
    item = todo["WorkItems"][index]
    item["kind"] = kind
    item["message"] = message
    item["done"] = True
    if summary:
        item["summary"] = summary
    item.update(extra or {})
    items: List[JsonDict] = list(todo["WorkItems"])
    items.insert(frontier, items.pop(index))
    todo["WorkItems"] = items
    return frontier


def closed_workitem_payload(todo: JsonDict, index: int, *, from_index: int) -> JsonDict:
    """The JSON a close command prints: what was closed, and where it landed."""
    node = todo["WorkItems"][index]
    payload: JsonDict = {
        "index": index,
        "from_index": from_index,
        "kind": node.get("kind", ""),
        "objid": node.get(todo_objid.OBJID_KEY, ""),
        "summary": node.get("summary", ""),
        "message": node.get("message", ""),
    }
    if node.get("at_sha"):
        payload["at_sha"] = node["at_sha"]
    return payload


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


# pylint: disable-next=too-many-locals
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


def reestablish_backlinks(
    root: Path, child: JsonDict, *, dry_run: bool = False
) -> List[str]:
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


# pylint: disable-next=too-many-arguments
def apply_ticket_path(
    root: Path,
    selector: str,
    jsonpath: str,
    value: Any,
    *,
    # pylint: disable-next=unused-argument
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


# pylint: disable-next=too-many-locals
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
    index = mark_cursor_done(
        parent, merge_subtodo_workitem(child_id, merge_sha, summary="")
    )
    if not parent["WorkItems"][index].get("summary"):
        parent["WorkItems"][index]["summary"] = merge_subject
    write_todo_worktree(root, parent)
    # State merged implies no linked worktree for the child (property of terminal).
    remove_todo_worktree_for_branch(root, child_branch)
    return {
        "child": child_id,
        "State": "merged",
        "merged_into": merge_target,
        "sha": merge_sha,
    }


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


# The three node kinds relto is legal on: Body itself, a Notes element, or a
# WorkItems element -- see IMPLEMENTATION.md / the relto design. Matched
# against todo_objid.iter_objects' dot-path spelling.
_RELTO_HOST_RE = re.compile(r"^(Body|Notes\.\d+|WorkItems\.\d+)$")


# The prose a derived mention is read from. A work item's ``message`` is
# deliberately absent: it is copied from git when the item completes and is
# not editable afterwards, so a relation derived from it could never be
# corrected -- only removed by rewriting history.
_MENTION_PROSE_FIELDS: Tuple[str, ...] = ("raw", "summary")


def _prose_targets(node: JsonDict) -> List[str]:
    """Every target *node*'s own editable prose names, first-occurrence order."""
    named: List[str] = []
    for field in _MENTION_PROSE_FIELDS:
        text = node.get(field)
        if not isinstance(text, str):
            continue
        for target in todo_ref.scan_targets(text):
            if target not in named:
                named.append(target)
    return named


def sync_mentions(todo: JsonDict) -> List[str]:
    """Reconcile every relto-bearing node's derived ``mention`` entries in place.

    A ``mention`` says "this node's prose names that target", so doctor owns it
    outright: it is added when the prose gains a target, dropped when the prose
    loses one, and never written by hand. Every entry of any OTHER type is left
    exactly as it stands -- same target, same type, same position -- which is
    the only rule that makes a derived field safe to edit by hand.

    A target a manual entry already carries is already related, so no second
    entry is derived for it; that keeps the one-host-one-target rule
    ``relto-add`` enforces.

    Returns one line per change, empty when the record already says what its
    prose says. Nothing is touched on a node that needs no change, so a second
    consecutive run allocates no objid and produces no write at all.
    """
    changes: List[str] = []
    for path, node in todo_objid.iter_objects(todo):
        if not _RELTO_HOST_RE.match(path):
            continue
        named = _prose_targets(node)
        existing = node.get("relto")
        existing = list(existing) if isinstance(existing, list) else []
        kept: List[Any] = []
        for element in existing:
            # A malformed element is relto_findings' to report, not this
            # function's to silently discard.
            if (
                not isinstance(element, dict)
                or element.get("type") != todo_ref.TYPE_MENTION
            ):
                kept.append(element)
                continue
            if element.get("target") in named:
                kept.append(element)
            else:
                changes.append(f"{path}: dropped mention of {element.get('target')}")
        carried = {e.get("target") for e in kept if isinstance(e, dict)}
        for target in named:
            if target in carried:
                continue
            kept.append({"type": todo_ref.TYPE_MENTION, "target": target})
            changes.append(f"{path}: derived mention of {target}")
        if kept == existing:
            continue
        if kept:
            node["relto"] = kept
        else:
            node.pop("relto", None)
    return changes


def _build_relto_element(target: str, rel_type: str) -> JsonDict:
    """Validate an explicit (target, type) pair and build one relto element.

    Shared by ``note-add``'s ``--relto=TARGET[:TYPE]`` parsing (``_parse_relto_arg``) and
    ``relto-add``'s separate ``--target``/``--type`` flags, so the relation-type allow-list
    check, the ``mention`` refusal, and the target-syntax check live in exactly one place.
    ``rel_type`` must be one of ``todo_ref.RELATION_TYPES``; ``mention`` is refused even
    though it is a valid type, since doctor derives and owns mention entries from a node's
    own prose and a hand-written one would immediately fight that sync. ``target`` is
    checked for SYNTAX only, via ``todo_ref.parse_target`` -- whether it resolves to
    anything is doctor's concern, not this one.
    """
    if rel_type not in todo_ref.RELATION_TYPES:
        allowed = ", ".join(sorted(todo_ref.RELATION_TYPES))
        raise TodoError(
            f"unknown relation type {rel_type!r}; expected one of {allowed}"
        )
    if rel_type == todo_ref.TYPE_MENTION:
        raise TodoError(
            "relto may not set type=mention by hand; doctor derives and owns mention "
            "entries from a node's own prose"
        )
    try:
        todo_ref.parse_target(target)
    except todo_ref.TodoRefError as exc:
        raise TodoError(str(exc)) from exc
    return {"target": target, "type": rel_type}


# pylint: disable-next=too-many-return-statements
def _recompute_auto_tags(
    todo: JsonDict,
) -> int:
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
        return subprocess.CompletedProcess(
            ["gh", *args], returncode=127, stdout="", stderr=str(exc)
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            ["gh", *args], returncode=1, stdout="", stderr=str(exc)
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            ["gh", *args],
            returncode=124,
            stdout="",
            stderr=f"gh timed out after {timeout}s",
        )


# pylint: disable-next=too-many-return-statements
def _gh_classify(
    result: subprocess.CompletedProcess[str],
) -> tuple[str, str, bool]:
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
        return (
            "GitHub API rate limit reached",
            "wait for the reset, or check: gh auth status",
            True,
        )
    for token in (
        "could not resolve host",
        "dial tcp",
        "connection refused",
        "network is unreachable",
    ):
        if token in low:
            return (
                "cannot reach GitHub",
                "check network/VPN, then re-run doctor",
                True,
            )
    if "could not resolve to a repository" in low or "not found" in low:
        return (
            "repo not found or no access",
            "check the repo slug and: gh auth status",
            False,
        )
    first = stderr.splitlines()[0] if stderr else f"gh exited {result.returncode}"
    return (
        f"gh failed: {first}",
        "run the gh command by hand to see the full error",
        False,
    )


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


# pylint: disable-next=too-many-return-statements
def gh_pr_for_todo(
    todo: JsonDict, root: Path
) -> tuple[Optional[JsonDict], Optional[str]]:
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
        payload, skip = _gh_json(
            "pr", "view", str(recorded), "-R", slug, "--json", fields
        )
        if skip:
            return (None, skip)
        return (payload if isinstance(payload, dict) else None, None)
    branch = todo.get("Branch")
    if not isinstance(branch, str) or not branch:
        return (None, "todo has no Branch to search for a PR")
    payload, skip = _gh_json(
        "pr",
        "list",
        "-R",
        slug,
        "--head",
        branch,
        "--state",
        "all",
        "--json",
        fields,
        "--limit",
        "1",
    )
    if skip:
        return (None, skip)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return (payload[0], None)
    return (None, None)  # no PR exists yet; not an error


# pylint: disable-next=too-many-locals
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
        target, kwargs = "merged", {
            "pr": number,
            "merge_commit": sha,
            "merged_into": pr.get("baseRefName"),
        }
    elif gh_state == "CLOSED":
        target, kwargs = "rejected", {
            "pr": number,
            "note": f"PR #{number} closed without merging",
        }
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


def _summary_snippet(text: str, limit: int = 60) -> str:
    """Collapse whitespace and truncate to a one-line commit subject."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _ticket_ids_in_paths(paths: Sequence[Path]) -> List[str]:
    """Short ids of ticket files among *paths*, in first-seen order."""
    ids: List[str] = []
    seen: set[str] = set()
    for path in paths:
        name = path.name
        if name.endswith(".json"):
            ident = name[: -len(".json")]
        elif name.endswith(".deleted"):
            ident = name[: -len(".deleted")]
        else:
            continue
        if len(ident) < 8 or any(ch not in "0123456789abcdef" for ch in ident):
            continue
        short = ident[:8]
        if short not in seen:
            seen.add(short)
            ids.append(short)
    return ids


def _git_with_index(
    root: Path, index: str, *args: str
) -> subprocess.CompletedProcess[str]:
    """Run git against *index* instead of the repository's real index."""
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = index
    return git_command.get_git().run(root, *args, env=env)


# pylint: disable-next=too-many-locals
def _commit_store_paths(root: Path, paths: Sequence[Path], message: str) -> None:
    """Commit *paths* in *root*, including deletions, and leave every other change alone.

    ``git commit -- paths`` is ``--only``: it takes the working-tree content of
    paths that still exist and drops a deletion ``git add -A`` had staged. A
    temporary index started from HEAD records the removed ticket and its
    tombstone in one commit, without sweeping unrelated staged files.
    """
    root_res = root.resolve()
    rels: List[str] = []
    for path in paths:
        try:
            rels.append(str(path.resolve().relative_to(root_res)))
        except ValueError as exc:
            raise TodoError(
                f"autocommit: {path} is outside git repository {root}"
            ) from exc
    # pylint: disable-next=consider-using-with
    handle = tempfile.NamedTemporaryFile(prefix="todo-autocommit-", delete=False)
    handle.close()
    index = handle.name
    try:
        head = run_git(root, "rev-parse", "--verify", "HEAD", check=False)
        base = (
            ["read-tree", "HEAD"] if head.returncode == 0 else ["read-tree", "--empty"]
        )
        seeded = _git_with_index(root, index, *base)
        if seeded.returncode != 0:
            detail = (seeded.stderr or seeded.stdout or "").strip()
            raise TodoError(f"autocommit failed: {detail}")
        added = _git_with_index(root, index, "add", "-A", "--", *rels)
        if added.returncode != 0:
            detail = (added.stderr or added.stdout or "").strip()
            raise TodoError(f"autocommit failed: {detail}")
        diff = _git_with_index(root, index, "diff", "--cached", "--quiet")
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            detail = (diff.stderr or diff.stdout or "").strip()
            raise TodoError(f"autocommit failed: {detail}")
        committed = _git_with_index(root, index, "commit", "-m", message)
        if committed.returncode != 0:
            detail = (committed.stderr or committed.stdout or "").strip()
            if "nothing to commit" in detail or "no changes added to commit" in detail:
                return
            raise TodoError(f"autocommit failed: {detail}")
    finally:
        try:
            os.unlink(index)
        except OSError:
            pass
    # The side index updated HEAD only. Refresh the real index for these paths
    # so a clean commit does not show up as unstaged, and leave other staged
    # paths untouched.
    refreshed = run_git(root, "add", "-A", "--", *rels, check=False)
    if refreshed.returncode != 0:
        detail = (refreshed.stderr or refreshed.stdout or "").strip()
        raise TodoError(f"autocommit failed: {detail}")


def _autopush(root: Path) -> None:
    """Push the store repo with its configured upstream."""
    pushed = run_git(root, "push", check=False)
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout or "").strip()
        raise TodoError(f"autopush failed: {detail}")

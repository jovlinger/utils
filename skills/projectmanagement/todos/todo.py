#!/usr/bin/env python3
"""AWS-style CLI for branch-bound todo tickets (sqlite-backed; legacy JSON import)."""

from __future__ import annotations

import argparse
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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
)

import git_command
import todo_db
import todo_objid
import todo_ref
import todo_store
import todo_embed
import todo_url
from todo_common import (
    JsonDict,
    SEARCH_STOPWORDS_KEY,
    TodoError,
    _json_embeddings_present,
    _merge_stored_embeddings,
    _strip_vectors_at,
    branch_exists,
    commit_exists,
    commit_todo,
    current_branch,
    current_state_name,
    find_todos_by_id,
    forest_roots,
    git_fetch_if_remote,
    git_url_for_repo,
    head_sha,
    id_matches,
    import_all_json_refs,
    import_json_ticket,
    is_all_selector,
    migrate_store,
    mint_id,
    normalize_todo_schema,
    read_todo_at_ref,
    read_todo_worktree,
    repo_root,
    resolve_ticket_by_id,
    run_git,
    run_search,
    sha_matches,
    todo_row,
    use_store,
    utc_now,
    write_todo_worktree,
)
from todo_ops import (
    SUBTODO_STATE_INFO,
    VALID_STATES,
    WORKITEM_BLOCKED,
    WORKITEM_CHECKPOINT,
    WORKITEM_CODE,
    WORKITEM_DONE_KINDS,
    WORKITEM_MERGE_SUBTODO,
    WORKITEM_NOCOMMIT_KINDS,
    WORKITEM_NULL_SHA,
    WORKITEM_OBJID_SCHEME,
    WORKITEM_OBSOLETE,
    WORKITEM_START_SUBTODO,
    WORKITEM_TASK,
    WORKTREE_TEARDOWN_STATES,
    _RELTO_HOST_RE,
    _autopush,
    _build_relto_element,
    _commit_store_paths,
    _recompute_auto_tags,
    _summary_snippet,
    _ticket_ids_in_paths,
    _workitem_index_by_number,
    apply_parent_links,
    apply_set_fields,
    apply_tag_add,
    apply_tag_clear,
    apply_tag_remove,
    apply_ticket_path,
    assert_todo_worktree_removable,
    build_ticket_skeleton,
    close_workitem,
    closed_workitem_payload,
    code_workitem,
    cursor_index,
    cursor_summary,
    ensure_todo_worktree,
    get_at_path,
    gh_gate_reason,
    is_done,
    kebab_branch_name,
    last_sha,
    load_json_file,
    mark_cursor_done,
    maybe_init_todo_branch,
    merge_subtodo,
    next_action,
    promote_groom_todo,
    reconcile_pr_state,
    reestablish_backlinks,
    remove_todo_worktree_for_branch,
    resolve_note_index,
    resolve_relto_host,
    resolve_workitem_index,
    set_at_path,
    set_state,
    start_subtodo_workitem,
    sync_mentions,
    teardown_worktree_for_terminal_state,
    upsert_subtodo,
    wait_for_state,
    workitem_is_done,
    workitem_kind,
    worktree_path_for_branch,
)


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

# File-store git sync, per todo dir in config.json. Each value is a list of
# subcommand class names (case-insensitive). A name matches that class and every
# subclass, so a non-leaf such as TodoFieldCommand covers set, read, rm, and the
# rest of that branch. Ignored for sqlite. A matching command commits the todo
# files it wrote (autocommit) or pushes the store repo (autopush); a read matches
# the class and still does nothing, because it wrote no file.
AUTOCOMMIT_KEY = "autocommit"
AUTOPUSH_KEY = "autopush"


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


class EditNotInteractive(TodoError):
    """An editor was needed but stdin/stdout are not a terminal to run it on."""


def _stdio_is_interactive() -> bool:
    """True only when both stdin and stdout are a tty (an editor can run)."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (ValueError, AttributeError):
        return False


def strip_leading_html_comments(text: str) -> str:
    """Drop the HTML comments and blank lines that lead *text*.

    Everything from the first other character on is returned verbatim, so a
    ``<!-- -->`` later in the text survives as markdown. A leading comment that
    is never closed raises TodoError, so it cannot silently empty the value.
    """
    rest = text
    while True:
        rest = rest.lstrip()
        if not rest.startswith("<!--"):
            return rest
        end = rest.find("-->", len("<!--"))
        if end < 0:
            raise TodoError("a leading <!-- comment is never closed; nothing written")
        rest = rest[end + len("-->") :]


def _run_editor(argv: Sequence[str]) -> int:
    """Run the editor command *argv* on the inherited terminal; return its exit status."""
    return subprocess.run(list(argv), check=False).returncode


def edit_text_via_editor(initial: str, *, prefix: str, header: str) -> Optional[str]:
    """Return what the user left after an editor ran on *initial*, or None if untouched.

    Opens ``$VISUAL`` (else ``$EDITOR`` else ``vi``) on a temp file holding
    *header* (an HTML comment), a blank line, then *initial* with a final
    newline. On read-back a file identical to the one written returns None;
    otherwise the leading HTML comments and blank lines are stripped (see
    ``strip_leading_html_comments``) and the rest returned. An editor that
    cannot start or exits nonzero raises TodoError. Precondition: a tty is
    available (see ``_stdio_is_interactive``).
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    body = initial if not initial or initial.endswith("\n") else initial + "\n"
    written = header.rstrip("\n") + "\n\n" + body
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".todoedit", prefix=f"{prefix}-", delete=False, encoding="utf-8"
    )
    try:
        handle.write(written)
        handle.close()
        try:
            status = _run_editor([*shlex.split(editor), handle.name])
        except OSError as exc:
            raise TodoError(f"could not run editor {editor!r}: {exc}") from exc
        if status != 0:
            raise TodoError(f"editor {editor!r} exited with status {status}; nothing written")
        with open(handle.name, encoding="utf-8") as fh:
            edited = fh.read()
        return None if edited == written else strip_leading_html_comments(edited)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


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


WORKITEM_KINDS = WORKITEM_DONE_KINDS | {WORKITEM_TASK}


WORKITEM_TARGET_HELP: str = (
    "which work item: an index (0-based; negative counts from the end) or "
    f"{WORKITEM_OBJID_SCHEME}<hex> (leading zeros optional). Defaults to the cursor"
)


# How a note is addressed, and the two things an omitted target can mean.
_NOTE_ADDRESS_HELP: str = (
    f"which note: an index (0-based; negative counts from the end) or "
    f"{WORKITEM_OBJID_SCHEME}<hex> (leading zeros optional)."
)

NOTE_TARGET_HELP: str = f"{_NOTE_ADDRESS_HELP} Omit to print every note"

NOTE_REQUIRED_TARGET_HELP: str = f"{_NOTE_ADDRESS_HELP} There is no cursor default"


# How a relto HOST is addressed -- one grammar serving all three relto-bearing
# node kinds, so relto-add/-remove/-read are one command family rather than a
# per-kind one. See resolve_relto_host.
RELTO_HOST_HELP: str = (
    "which relto-bearing node: 'body' (the Body field's own relto list), "
    f"{todo_ref.OBJID_SCHEME}<hex> (4+ hex, record-wide -- any object in the record, checked "
    "against the three legal relto hosts), or note:<index> / workitem:<index> (0-based, "
    "negative counting from the end)"
)


def require_open_workitem(todo: JsonDict, index: int) -> JsonDict:
    """Return the work item at *index*, refusing a done one (invariant #3).

    Done items form the prefix of the plan and are its history, so only the
    not-done frontier can be edited. An edit aimed at a done item is
    an error rather than a silent no-op: it is a misaddressed command, and
    rewriting history is what invariant #3 exists to prevent.
    """
    item = todo["WorkItems"][index]
    if not isinstance(item, dict) or workitem_is_done(item):
        raise TodoError(
            f"work item {index} is done; only the not-done frontier can be edited "
            "(done items are this todo's history -- invariant #3)"
        )
    return item


# Recorded on a checkpoint whose caller gave no -m, so the trail never
# inherits the HEAD commit's own message and pretends it described the step.
NOOP_CHECKPOINT_MESSAGE = "(no-op checkpoint; no commit produced)"


# A path names a Notes element (and only a Notes element) when it matches this
# -- the narrower sibling of ``_RELTO_HOST_RE`` (todo.py:3395), which also
# accepts Body and WorkItems.N. prompt propagates notes and nothing else, so
# it needs the narrower test.
_NOTE_PATH_RE = re.compile(r"^Notes\.\d+$")


def _prompt_notes(todo: JsonDict, node: JsonDict, seen_notes: set) -> List[str]:
    """Sections for every note reachable from *node*'s ``relto``, depth-first.

    *node* is ``Body`` or a ``Notes`` element of *todo*; *seen_notes* is keyed
    by ``(todo Id, note objid)`` and shared across the WHOLE prompt run (every
    record in the chain), so a note already emitted anywhere is never emitted
    twice -- the same discipline ``build_prompt_chain`` already applies to a
    shared ancestor, membership checked before descent. A target's fate: one
    naming a work item, a subtodo, or anything but a ``Notes`` element resolves
    to nothing (``prompt`` has never propagated ``AC`` or ``WorkItems``, and a
    relto target is not a way around that); an unresolvable local target is
    silently dropped (a dangling target is a doctor finding, not a prompt
    failure); a ``todo:`` or cross-todo target is never chased -- this record
    only -- and prints a one-line pointer naming the target instead; a local
    target naming a note descends into that note's own ``relto`` in turn, so
    the walk is transitive within this record and cycle-safe via *seen_notes*.
    """
    sections: List[str] = []
    tid = str(todo.get("Id", ""))
    for element in node.get("relto") or []:
        target_str = element.get("target") if isinstance(element, dict) else None
        if not isinstance(target_str, str):
            continue
        try:
            target = todo_ref.parse_target(target_str)
        except todo_ref.TodoRefError:
            continue
        if not target.is_local:
            sections.append(f"===== [not followed: {target.raw}] =====")
            continue
        try:
            path = todo_ref.resolve_local(todo, target)
        except todo_ref.TodoRefError:
            continue
        if not _NOTE_PATH_RE.match(path):
            continue
        note = get_at_path(todo, path)
        objid = note.get(todo_objid.OBJID_KEY, "")
        key = (tid, objid)
        if key in seen_notes:
            continue
        seen_notes.add(key)
        raw = note.get("raw", "")
        sections.append(f"===== note [objid:{objid}] =====\n{raw}".rstrip())
        sections.extend(_prompt_notes(todo, note, seen_notes))
    return sections


def _prompt_section(todo: JsonDict, seen_notes: set) -> str:
    """Render one todo as Summary/Body plus its reachable notes, for the prompt chain.

    Notes reachable from ``Body.relto`` (transitively, notes-only, this record
    only -- see ``_prompt_notes``) are appended after Body, each under its own
    header carrying the note's objid so an agent can cite the fact it used.
    *seen_notes* is the whole run's note de-dup set, threaded through so a note
    already emitted -- from this record or an earlier one in the chain -- is
    not emitted twice.
    """
    tid = str(todo.get("Id", ""))[:8]
    summary_obj = todo.get("Summary")
    summary = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
    body_obj = todo.get("Body")
    body = body_obj.get("raw", "") if isinstance(body_obj, dict) else ""
    header = f"===== {summary} [{tid}] =====".strip()
    parts = [f"{header}\n{body}".rstrip()]
    if isinstance(body_obj, dict):
        parts.extend(_prompt_notes(todo, body_obj, seen_notes))
    return "\n\n".join(parts)


def build_prompt_chain(root: Path, selector: str) -> str:
    """Concatenate a todo and its parent chain into one startup prompt.

    Walks the ``Parent`` list up (context references included), depth-first, so
    the farthest ancestors' 'why' comes first and the target's own body is last.
    De-duplicates shared ancestors, is cycle-safe, and notes any parent that
    cannot be resolved in this db rather than dropping it silently. Read-only:
    parents are resolved from the db with no branch checkout. Each record's
    section also carries the notes reachable from its own Body.relto (see
    _prompt_notes); seen_notes de-dupes those across the whole chain, not just
    within one record.
    """
    _loc, target = resolve_ticket_by_id(root, selector)
    sections: List[str] = []
    seen: set[str] = set()
    seen_notes: set = set()

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
        sections.append(_prompt_section(todo, seen_notes))

    visit(target)
    return "\n\n".join(sections)


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
        "Notes",
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
        if k in (WORKITEM_BLOCKED, WORKITEM_OBSOLETE):
            # For both of these the reason is the item's whole content: without
            # it the trail says a step stopped and nothing about why, which is
            # what deleting it would have said.
            if not (isinstance(item.get("message"), str) and item.get("message").strip()):
                findings.append(
                    f"WorkItems.{index} {k} item is missing a message; why a step was "
                    "closed without a commit IS the record"
                )
            for field in ("sha", "at_sha"):
                if item.get(field):
                    findings.append(
                        f"WorkItems.{index} {k} item carries {field}; it produced no commit "
                        "and observed no position"
                    )
    # a done todo must not end in start_subtodo, any of the no-commit kinds, or
    # a no-change sentinel -- it must be a real code/merge commit so last-sha is
    # the branch's last commit (#6). A todo whose final act produced no commit
    # has not finished, it has stopped: nothing was landed, and last-sha would
    # have to lie or be empty.
    if items and is_done(todo):
        last = items[-1]
        if isinstance(last, dict) and workitem_kind(last) in (
            WORKITEM_START_SUBTODO,
            *WORKITEM_NOCOMMIT_KINDS,
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


def notes_findings(todo: JsonDict) -> List[str]:
    """Hard findings for the optional ``Notes`` field's shape.

    ``Notes`` is optional; when present it must be a list whose every element
    is an object carrying only ``objid``, ``raw``, and optional ``relto`` --
    no ``kind``, no ``done``, no status of any sort, since a note is a fact
    and a fact has no disposition to record. ``relto``'s own shape is checked
    separately by ``relto_findings``, since that field also legally appears
    on ``Body`` and on ``WorkItems`` elements.
    """
    findings: List[str] = []
    notes = todo.get("Notes")
    if notes is None:
        return findings
    if not isinstance(notes, list):
        return ["Notes must be a list"]
    for index, element in enumerate(notes):
        if not isinstance(element, dict):
            findings.append(f"Notes.{index} must be an object")
            continue
        extra = sorted(set(element) - {todo_objid.OBJID_KEY, "raw", "relto"})
        if extra:
            findings.append(f"Notes.{index} has unexpected fields: {', '.join(extra)}")
        raw = element.get("raw")
        if not isinstance(raw, str) or not raw:
            findings.append(f"Notes.{index}.raw must be a non-empty string")
    return findings


def relto_findings(todo: JsonDict) -> List[str]:
    """Hard findings for every ``relto`` list found anywhere in *todo*.

    A ``relto`` element holds exactly ``objid``, ``type`` and ``target``:
    ``type`` must be one of ``todo_ref.RELATION_TYPES`` and ``target`` must
    parse per ``todo_ref.parse_target`` (syntax only -- whether the target
    actually resolves is doctor's mention-sync concern, not this one).
    ``relto`` itself is legal only on ``Body``, a ``Notes`` element, or a
    ``WorkItems`` element; found anywhere else, its mere presence is a finding.
    """
    findings: List[str] = []
    for path, obj in todo_objid.iter_objects(todo):
        relto = obj.get("relto")
        if relto is None:
            continue
        if not _RELTO_HOST_RE.match(path):
            findings.append(
                f"{path}.relto is not allowed here; relto is legal only on Body, a "
                "Notes element, or a WorkItems element"
            )
            continue
        if not isinstance(relto, list):
            findings.append(f"{path}.relto must be a list")
            continue
        for index, element in enumerate(relto):
            label = f"{path}.relto.{index}"
            if not isinstance(element, dict):
                findings.append(f"{label} must be an object")
                continue
            extra = sorted(set(element) - {todo_objid.OBJID_KEY, "type", "target"})
            if extra:
                findings.append(f"{label} has unexpected fields: {', '.join(extra)}")
            rel_type = element.get("type")
            if rel_type not in todo_ref.RELATION_TYPES:
                findings.append(f"{label}.type {rel_type!r} is not a known relation type")
            try:
                parsed = todo_ref.parse_target(element.get("target"))
            except todo_ref.TodoRefError as exc:
                findings.append(f"{label}.target: {exc}")
                continue
            # A LOCAL target is checkable here and now, and a dead one is a
            # dead citation: the prose or the manual entry names an object
            # this record does not have. A cross-todo target needs another
            # record, so it is doctor_warnings' business instead.
            if parsed.is_local:
                try:
                    todo_ref.resolve_local(todo, parsed)
                except todo_ref.TodoRefError as exc:
                    findings.append(f"{label}.target: {exc}")
    return findings


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
    findings.extend(notes_findings(todo))
    findings.extend(relto_findings(todo))
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
    for path, node in todo_objid.iter_objects(todo):
        if not _RELTO_HOST_RE.match(path):
            continue
        for index, element in enumerate(node.get("relto") or []):
            if not isinstance(element, dict):
                continue
            try:
                parsed = todo_ref.parse_target(element.get("target"))
            except todo_ref.TodoRefError:
                continue  # relto_findings owns the syntax complaint
            if parsed.is_local:
                continue  # checkable here, so it is a finding instead
            label = f"{path}.relto.{index}.target {parsed.raw}"
            try:
                _loc, other = resolve_ticket_by_id(root, parsed.todo_prefix)
            except TodoError:
                warnings.append(f"{label}: todo not discoverable here")
                continue
            if parsed.is_remote:
                try:
                    todo_ref.resolve_local(other, todo_ref.OBJID_SCHEME + parsed.objid_prefix)
                except todo_ref.TodoRefError as exc:
                    warnings.append(f"{label}: {exc}")
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

    def __init__(self, args: argparse.Namespace, *, todo_dir: Path) -> None:
        """Copy parsed argparse fields onto the command object.

        ``todo_dir`` is the store directory resolved once in ``main`` before any
        subcommand runs (``$TODO_DIR``, then the ``.todo`` walk). Every
        subcommand receives that same path as ``self.todo_dir``.
        """
        self.args = args
        for name, value in vars(args).items():
            if name != "command_cls":
                setattr(self, name, value)
        # After the argparse copy so a flag cannot clobber the resolved path.
        self.todo_dir = todo_dir

    def __getattr__(self, name: str) -> Any:
        """Expose argparse fields as dynamic command attributes."""
        return getattr(self.args, name)

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


class NoteCommand(CommandGroup):
    """Acts on a todo's Notes -- status-free facts and findings, cross-referenced by objid."""

    group_title: ClassVar[str] = "Note"


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
    NoteCommand,
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
        "`init` later creates a well-named branch. To edit one free-text field in "
        "$VISUAL/$EDITOR, use `edit`."
    )

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


_WORKITEM_PATH_RE = re.compile(r"\AWorkItems\.(\d+)\Z")
_NOTE_RAW_PATH_RE = re.compile(r"\ANotes\.\d+\.raw\Z")


def resolve_edit_target(todo: JsonDict, target: str) -> str:
    """Return the dot path of the free-text string *target* names in *todo*.

    ``objid:<hex>`` (leading zeros optional) must name a note, edited at its
    ``raw``, or a work item, done or not, edited at its ``summary``. Anything else is a dot path in
    the get-json-path grammar: a string is edited as is, and an object whose
    ``raw`` is a string (Summary, Body, LongSummary, a note) is edited at its
    ``raw``. Every other target raises TodoError.
    """
    if target.startswith(WORKITEM_OBJID_SCHEME):
        prefix = target[len(WORKITEM_OBJID_SCHEME) :]
        if not prefix or not todo_objid.is_objid_prefix(prefix):
            raise TodoError(f"objid {prefix!r} is not lowercase hex")
        try:
            path = todo_ref.resolve_local(
                todo, WORKITEM_OBJID_SCHEME + todo_objid.normalize_objid_prefix(prefix)
            )
        except todo_ref.TodoRefError as exc:
            raise TodoError(str(exc)) from exc
        if _NOTE_PATH_RE.match(path):
            return f"{path}.raw"
        if _WORKITEM_PATH_RE.match(path):
            return f"{path}.summary"
        raise TodoError(
            f"{target} names {path}, not a note or work item; address it by dot path instead"
        )
    value = get_at_path(todo, target)
    if isinstance(value, str):
        return target
    if isinstance(value, dict) and isinstance(value.get("raw"), str):
        return f"{target}.raw"
    raise TodoError(f"{target} is not free text (it holds a {type(value).__name__})")


class EditCommand(TodoFieldCommand):
    command_names = ("edit",)
    doc_short: ClassVar[str] = "Edit a free-text field in $VISUAL/$EDITOR"
    doc_long: ClassVar[str] = (
        "Edit opens $VISUAL (else $EDITOR, else vi) on a temp file holding an HTML comment "
        "header naming the todo and target, then the current text of one free-text field of "
        "the selected todo. It stores what the editor leaves, minus leading HTML comments and "
        "blank lines and with surrounding whitespace trimmed; a comment after the first other "
        "line is kept. A file saved untouched writes nothing, so a value that itself begins "
        "with <!-- survives a no-op edit but loses that leading comment on a real one. An "
        "empty result stores the empty string, except for a note, whose text must be "
        "non-empty. TARGET is either a dot path in the get-json-path grammar (Summary, Body, "
        "AC, LongSummary, ActualSummary, Notes.0, ...) -- naming a string, or an object whose "
        "raw is a string, which is then edited at its raw -- or objid:<hex> (leading zeros "
        "optional) naming a note, edited at its raw (its objid and relto survive), or a work "
        "item, done or not, edited at its summary (its objid and status survive). Refused "
        "with exit 1 and nothing written: stdin/stdout not a terminal, a target that is not "
        "free text, a leading <!-- that is never closed, an empty note, and an editor that "
        "fails or exits nonzero. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register edit arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument(
            "target",
            help="dot path (e.g. Body, Summary, AC, Notes.0) or objid:<hex> of a note or "
            "work item",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Edit the target's current text in an editor; store it when it changed."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        path = resolve_edit_target(todo, self.target)
        if not _stdio_is_interactive():
            raise EditNotInteractive("edit requires an interactive terminal; nothing written")
        current: str = get_at_path(todo, path)
        short_id = str(todo.get("Id", ""))[:8]
        what = path if self.target == path else f"{self.target} ({path})"
        header = (
            f"<!-- editing todo:{short_id} {what}\n"
            "     Leading HTML comments and blank lines are stripped on save. -->\n"
        )
        result = edit_text_via_editor(
            current, prefix=f"{short_id}-{path.replace('.', '-')}", header=header
        )
        edited = current.strip() if result is None else result.strip()
        if edited == current.strip():
            print(f"todo: {self.target} unchanged; nothing written", file=sys.stderr)
            return 0
        if not edited and _NOTE_RAW_PATH_RE.match(path):
            raise TodoError(
                f"{path} must be non-empty (doctor requires note text); nothing written"
            )
        set_at_path(todo, path, edited)
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): edit {path}")
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
        if sweep and todo_store.config_list(self.todo_dir, SEARCH_STOPWORDS_KEY):
            todo_store.update_config(self.todo_dir, {SEARCH_STOPWORDS_KEY: None})
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
        "it records the branch's most recent commit, or a --sha that must name HEAD -- the full "
        "sha or a 4+ char prefix of it (mismatch exits 1). If the tree is dirty it commits all "
        "updates and new files (git add -A) and "
        "records the new HEAD sha; the commit message is -m when given, else the work item's "
        "summary. It adds no bookkeeping commit, so the recorded sha stays the branch HEAD "
        "(invariant #6). --summary overrides the item's high-level description (defaults to the "
        "cursor task's summary). It does ONE thing -- record a commit -- because the dispositions "
        "that record no commit are their own commands: work-item-checkpoint (the step finished "
        "without one), work-item-blocked (it cannot be done as written), work-item-obsolete (it "
        "is no longer wanted). Those need no commit and, unlike this command, can close an item "
        "other than the cursor. Like State metadata, inapplicable flags raise rather than being "
        "silently dropped: -m on a clean tree, or --sha on a dirty one, is an error."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-done arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("-m", "--message", help="commit message for a dirty tree (defaults to the work item summary)")
        parser.add_argument("--sha", help="commit sha (full, or a 4+ char prefix) for a clean tree; must name HEAD")
        parser.add_argument("--summary", help="override the work item's high-level description")
        # Migration stubs. Both moved to commands of their own, because a
        # disposition that records no commit has no business being a flag on
        # the command whose whole job is recording one. Kept registered, and
        # hidden, so the old spelling answers with a pointer rather than
        # argparse's bare "unrecognized arguments".
        parser.add_argument("--checkpoint", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument("--blocked", action="store_true", help=argparse.SUPPRESS)

    def do(self) -> int:
        """Complete the cursor work item as code (invariant #1).

        Post-condition: the branch is fully committed. A clean tree records the
        current HEAD; a dirty tree commits all updates and new files first."""
        for flag, moved_to, why in (
            (
                "checkpoint",
                "work-item-checkpoint <id> [target] [-m ...]",
                "it records HEAD as the observational at_sha, and can close an item other "
                "than the cursor",
            ),
            (
                "blocked",
                "work-item-blocked <id> [target] -m ...",
                "it is store-only -- no branch checkout and no clean tree, since nothing it "
                "records comes from git",
            ),
        ):
            if getattr(self, flag):
                raise TodoError(f"--{flag} is now `todo.py {moved_to}`: {why}")
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
                    "recorded); commit the work first, or use work-item-checkpoint for a step "
                    "that finished without a commit, or work-item-blocked for one that cannot "
                    "be done as written"
                )
            head = head_sha(root)
            if not head:
                raise TodoError("no commits on branch; cannot record a code work item")
            if self.sha and not sha_matches(head, self.sha):
                if len(self.sha) < todo_url.MIN_PREFIX:
                    raise TodoError(
                        f"--sha {self.sha!r} is shorter than {todo_url.MIN_PREFIX} characters; "
                        "pass a longer prefix or the full sha"
                    )
                raise TodoError(
                    f"--sha {self.sha!r} does not match HEAD {head!r}; "
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
    doc_short: ClassVar[str] = "Read the cursor, or any, work item"
    doc_long: ClassVar[str] = (
        "Work-item-read prints the current work item -- the cursor, which is the first not-done "
        "item -- with its index, plus whether the todo is done. Index is null when there is no "
        "open item. It also emits a 'next' object: the deterministic mechanical command to advance "
        "the loop ({action, command}), including the finish sequence when the todo is done. 'next' "
        "is a mechanism hint, not policy -- a plain task defaults to work-item-done, but the agent "
        "may instead split it or turn it into a subtodo per the skill's dispatch table. An "
        "explicit TARGET (an index, negative counting from the end, or objid:<hex>) reads that "
        "item instead, done items included -- reading is not editing. 'next' still describes the "
        "CURSOR whatever item is read, since it is the todo's next mechanical step, not the "
        "target's."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-read arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)

    def do(self) -> int:
        """Print the cursor work item, or the addressed one, for the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        # No target and no open item is not an error here: the empty cursor is
        # exactly what a polling worker needs to see (index null, is_done true).
        index = (
            cursor_index(todo)
            if self.target is None
            else resolve_workitem_index(todo, self.target, what="read")
        )
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


def _parse_relto_arg(value: str) -> JsonDict:
    """Parse one ``--relto=TARGET[:TYPE]`` value into a relto element.

    A target itself contains colons (``objid:0034``, ``todo:c03d/objid:0045``),
    so there is no separator that is safe to split on unconditionally. Instead:
    split on the LAST colon, and treat the suffix as a relation TYPE only when
    it is one of ``todo_ref.RELATION_TYPES`` -- otherwise the whole value is
    the target and the type defaults to ``todo_ref.TYPE_RELATES``. The allow-list
    check and the ``mention`` refusal are ``_build_relto_element``'s; this only
    does the split.
    """
    if not value:
        raise TodoError("--relto needs a value, e.g. --relto=objid:0034 or objid:0034:relates")
    head, sep, suffix = value.rpartition(":")
    if sep and suffix in todo_ref.RELATION_TYPES:
        target, rel_type = head, suffix
    else:
        target, rel_type = value, todo_ref.TYPE_RELATES
    return _build_relto_element(target, rel_type)


class NoteAddCommand(NoteCommand):
    command_names = ("note-add",)
    doc_short: ClassVar[str] = "Append a note"
    doc_long: ClassVar[str] = (
        "Note-add appends a status-free fact or finding to the selected todo's Notes list and "
        "PRINTS the new note's objid on stdout, because that objid is the handle every "
        "cross-reference needs -- unlike work-item-add, which prints nothing. A note carries "
        "exactly raw text plus an optional relto list: no kind, no done, no status of any sort, "
        "since a fact has no disposition to record. --relto (repeatable) adds a cross-reference: "
        "TARGET[:TYPE] where TARGET is a qualified target (objid:<hex> in this record, "
        "todo:<hex> for a whole todo, or todo:<hex>/objid:<hex> for an object in another todo's "
        "record) and the optional ':TYPE' suffix is checked against the relation-type allow-list "
        "and split off the LAST colon only, since a target itself contains colons; a value with "
        "no recognized type suffix is the target as-is, with type defaulting to 'relates'. "
        "'mention' is refused from the command line -- doctor derives and owns mention entries "
        "from a node's own prose. The write is store-only, so it works equally on a branchless "
        "groom todo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register note-add arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("--raw", required=True, help="the fact or finding")
        parser.add_argument(
            "--relto",
            action="append",
            metavar="TARGET[:TYPE]",
            help="cross-reference (repeatable); TYPE defaults to 'relates' and 'mention' is "
            "refused here -- doctor owns mention entries",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Append a note to the selected todo and print its new objid."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        if not self.raw.strip():
            raise TodoError("--raw must not be blank")
        relto = [_parse_relto_arg(value) for value in (self.relto or [])]
        note: JsonDict = {"raw": self.raw}
        if relto:
            note["relto"] = relto
        notes: List[JsonDict] = list(todo.get("Notes") or [])
        notes.append(note)
        todo["Notes"] = notes
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): add note: {_summary_snippet(self.raw)}")
        print(note[todo_objid.OBJID_KEY])
        return 0


class NoteReadCommand(NoteCommand):
    command_names = ("note-read",)
    doc_short: ClassVar[str] = "Read one note, or every note"
    doc_long: ClassVar[str] = (
        "Note-read prints one note as JSON when TARGET is given -- an index (0-based, negative "
        "counting from the end) or objid:<hex> (leading zeros optional), the same addressing "
        "grammar work-item commands use -- or every note as a JSON list when TARGET is omitted. "
        "This deliberately differs from work-item-read, which defaults an omitted target to the "
        "cursor: a note has no status, so there is no cursor to default to, and 'every note' is "
        "the only sensible reading of a bare selector. The read is store-only and works equally "
        "on a branchless groom todo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register note-read arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=NOTE_TARGET_HELP)

    def do(self) -> int:
        """Print one note, or every note, for the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        notes: List[JsonDict] = list(todo.get("Notes") or [])
        if self.target is None:
            print(json.dumps(notes, indent=2))
            return 0
        index = resolve_note_index(todo, self.target)
        print(json.dumps(notes[index], indent=2))
        return 0


class NoteReplaceCommand(NoteCommand):
    command_names = ("note-replace",)
    doc_short: ClassVar[str] = "Overwrite a note's text"
    doc_long: ClassVar[str] = (
        "Note-replace overwrites the addressed note's raw text in place. TARGET is required -- "
        "an index (0-based, negative counting from the end) or objid:<hex> (leading zeros "
        "optional) -- since a note has no cursor to default to. Both the objid and any existing "
        "relto list survive untouched: the objid because a note is a permanent handle other "
        "records cite, and relto because rewording the fact is not the same act as retargeting "
        "its cross-references. A note carries no status and no done prefix, so there is nothing "
        "here to restrict -- the write applies to any note at any time, regardless of the "
        "todo's State. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register note-replace arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", help=NOTE_REQUIRED_TARGET_HELP)
        parser.add_argument("--raw", required=True, help="the replacement fact or finding")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Overwrite the addressed note's raw text, keeping its objid and relto."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        if not self.raw.strip():
            raise TodoError("--raw must not be blank")
        index = resolve_note_index(todo, self.target)
        notes: List[JsonDict] = list(todo.get("Notes") or [])
        # PATCH the node; never delete-and-recreate it -- the objid and relto
        # are the note's identity, not its content, so both survive untouched.
        notes[index]["raw"] = self.raw
        todo["Notes"] = notes
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): replace note: {_summary_snippet(self.raw)}")
        print(json.dumps({"index": index, "raw": self.raw}, indent=2))
        return 0


class NoteDeleteCommand(NoteCommand):
    command_names = ("note-delete",)
    doc_short: ClassVar[str] = "Delete a note"
    doc_long: ClassVar[str] = (
        "Note-delete erases the addressed note node outright. TARGET is required -- an index "
        "(0-based, negative counting from the end) or objid:<hex> (leading zeros optional) -- "
        "since a note has no cursor to default to. A note carries no status and no done prefix, "
        "so there is nothing here to restrict -- any note can be deleted at any time, regardless "
        "of the todo's State. A relto element elsewhere that targets the deleted objid is left "
        "as-is: a target left pointing at nothing becomes a doctor finding, not a refusal here. "
        "Deleting the last remaining note drops the Notes field entirely, matching absent-means-"
        "none: an empty list is equivalent to no field and is not written. The write is "
        "store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register note-delete arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", help=NOTE_REQUIRED_TARGET_HELP)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Delete the addressed note."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        index = resolve_note_index(todo, self.target)
        notes: List[JsonDict] = list(todo.get("Notes") or [])
        removed = notes.pop(index)
        if notes:
            todo["Notes"] = notes
        else:
            todo.pop("Notes", None)
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(
                root, f"chore(todo): delete note: {_summary_snippet(removed.get('raw', ''))}"
            )
        print(json.dumps({"deleted_index": index, "raw": removed.get("raw", "")}, indent=2))
        return 0


def _relto_read_all(todo: JsonDict) -> List[JsonDict]:
    """Every relation anywhere in *todo*, one entry per relto element.

    Walks the same ``_RELTO_HOST_RE``-filtered hosts ``relto_findings`` checks, in the
    same depth-first record order (Body, then Notes, then WorkItems), so the whole
    cross-reference graph of one todo comes back in one deterministic list. Each entry
    carries the host's own json path and objid alongside the relation's own objid, type
    and target.
    """
    entries: List[JsonDict] = []
    for path, obj in todo_objid.iter_objects(todo):
        if not _RELTO_HOST_RE.match(path):
            continue
        for element in obj.get("relto") or []:
            if not isinstance(element, dict):
                continue  # doctor reports the shape; a read should not traceback on it
            entries.append(
                {
                    "host_path": path,
                    "host_objid": obj.get(todo_objid.OBJID_KEY),
                    todo_objid.OBJID_KEY: element.get(todo_objid.OBJID_KEY),
                    "type": element.get("type"),
                    "target": element.get("target"),
                }
            )
    return entries


class RelToAddCommand(NoteCommand):
    command_names = ("relto-add",)
    doc_short: ClassVar[str] = "Add a cross-reference to a relto-bearing node"
    doc_long: ClassVar[str] = (
        "Relto-add appends one cross-reference to the addressed HOST's relto list. HOST is "
        "one command family serving all three relto-bearing node kinds, not a per-kind one: "
        "'body' for the Body field's own list, objid:<hex> (4+ hex, record-wide) for any object "
        "in the record -- resolved exactly as a permalink resolves objid:<hex>, then checked "
        "against the three legal relto hosts, so an objid landing on a Tag or a Subtodos entry "
        "is refused naming what it hit -- or note:<index> / workitem:<index> (0-based, negative "
        "counting from the end) against the Notes or WorkItems list. --target is a qualified "
        "target (objid:<hex> in this record, todo:<hex> for a whole todo, or "
        "todo:<hex>/objid:<hex> for an object in another todo's record), checked for SYNTAX "
        "only -- whether it resolves to anything is doctor's concern, not this one. --type "
        "defaults to 'relates' and is checked against the relation-type allow-list; 'mention' "
        "is refused -- doctor derives and owns mention entries from a node's own prose, so a "
        "hand-written one is an assertion nobody made. A host relates to a target once: adding "
        "a target the host's relto already carries is an error, whatever the existing entry's "
        "type is. The write is store-only, so it works equally on a branchless groom todo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register relto-add arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("host", help=RELTO_HOST_HELP)
        parser.add_argument("--target", required=True, help="qualified target, e.g. objid:0034")
        parser.add_argument(
            "--type",
            default=todo_ref.TYPE_RELATES,
            help="relation type (default 'relates'); 'mention' is refused here",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Append one relto element to the addressed host and print it."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        path = resolve_relto_host(todo, self.host)
        node = get_at_path(todo, path)
        element = _build_relto_element(self.target, self.type)
        relto: List[JsonDict] = list(node.get("relto") or [])
        if any(existing.get("target") == element["target"] for existing in relto):
            raise TodoError(f"{path} already relates to {element['target']!r}")
        relto.append(element)
        node["relto"] = relto
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): relto-add {path} -> {element['target']}")
        print(json.dumps(element, indent=2))
        return 0


class RelToRemoveCommand(NoteCommand):
    command_names = ("relto-remove",)
    doc_short: ClassVar[str] = "Remove a cross-reference from a relto-bearing node"
    doc_long: ClassVar[str] = (
        "Relto-remove drops one cross-reference from the addressed HOST's relto list, matched "
        "by --target against the exact stored string -- not a prefix. HOST takes the same "
        "spellings relto-add does: 'body', objid:<hex> (4+ hex, record-wide, checked against "
        "the three legal relto hosts), or note:<index> / workitem:<index>. A target the host "
        "does not carry is an error. Removing an entry whose type is 'mention' is refused: "
        "doctor would re-derive it on the very next run, so the only way to drop a mention is "
        "to edit the node's own prose so the target no longer appears there. The write is "
        "store-only, so it works equally on a branchless groom todo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register relto-remove arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("host", help=RELTO_HOST_HELP)
        parser.add_argument("--target", required=True, help="the exact stored target to remove")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Remove one relto element from the addressed host, matched by exact target."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        path = resolve_relto_host(todo, self.host)
        node = get_at_path(todo, path)
        relto: List[JsonDict] = list(node.get("relto") or [])
        index = next(
            (i for i, element in enumerate(relto) if element.get("target") == self.target), None
        )
        if index is None:
            raise TodoError(f"{path} has no relto entry targeting {self.target!r}")
        if relto[index].get("type") == todo_ref.TYPE_MENTION:
            raise TodoError(
                f"{path}.relto.{index} is a mention entry; doctor would re-derive it on the "
                "next run -- edit the node's prose instead so the target no longer appears there"
            )
        removed = relto.pop(index)
        if relto:
            node["relto"] = relto
        else:
            node.pop("relto", None)
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): relto-remove {path} -> {removed['target']}")
        print(json.dumps(removed, indent=2))
        return 0


class RelToReadCommand(NoteCommand):
    command_names = ("relto-read",)
    doc_short: ClassVar[str] = "Read one host's relations, or every relation in the record"
    doc_long: ClassVar[str] = (
        "Relto-read prints the addressed HOST's relto list as JSON when HOST is given, or "
        "every relation anywhere in the record as a JSON list when HOST is omitted. HOST takes "
        "the same spellings relto-add does: 'body', objid:<hex> (4+ hex, record-wide, checked "
        "against the three legal relto hosts), or note:<index> / workitem:<index> (0-based, "
        "negative counting from the end). With no host, each entry in the printed list carries "
        "the host's own json path and objid alongside the relation's own objid, type and "
        "target, so the whole cross-reference graph of one todo is visible in one call. The "
        "read is store-only and works equally on a branchless groom todo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register relto-read arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("host", nargs="?", help=RELTO_HOST_HELP)

    def do(self) -> int:
        """Print one host's relations, or every relation, for the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        if self.host is None:
            print(json.dumps(_relto_read_all(todo), indent=2))
            return 0
        path = resolve_relto_host(todo, self.host)
        node = get_at_path(todo, path)
        print(json.dumps(node.get("relto") or [], indent=2))
        return 0


class WorkItemInsertCommand(WorkItemEditCommand):
    command_names = ("work-item-insert",)
    doc_short: ClassVar[str] = "Insert a task in the plan"
    doc_long: ClassVar[str] = (
        "Work-item-insert adds a not-done task at the cursor so it becomes the current item, "
        "pushing the existing frontier down (used to explode a step into finer steps). It appends "
        "when the todo has no open item. An explicit TARGET (an index, negative counting from the "
        "end, or objid:<hex>) inserts BEFORE that item instead, pushing it down -- the same "
        "operation aimed further down the plan, so the target must itself be a not-done item. "
        "Appending is work-item-add, not an insert past the end. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-insert arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Insert a not-done task at the cursor, or before the addressed item."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        new_item = {"kind": WORKITEM_TASK, "summary": self.summary, "done": False}
        if self.target is None:
            # The cursor default appends on a finished plan (nothing to push
            # down); an explicit target always names an item to push down.
            index = cursor_index(todo)
            if index is None:
                items.append(new_item)
                index = len(items) - 1
            else:
                items.insert(index, new_item)
        else:
            index = resolve_workitem_index(todo, self.target, what="insert before")
            require_open_workitem(todo, index)
            items.insert(index, new_item)
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): insert work item: {_summary_snippet(self.summary)}")
        print(json.dumps({"index": index, "summary": self.summary}, indent=2))
        return 0


class WorkItemReplaceCommand(WorkItemEditCommand):
    command_names = ("work-item-replace",)
    doc_short: ClassVar[str] = "Reword a not-done work item"
    doc_long: ClassVar[str] = (
        "Work-item-replace rewrites a not-done task's freetext summary, leaving it not-done. It "
        "acts on the cursor by default; an explicit TARGET (an index, negative counting from the "
        "end, or objid:<hex>) rewords that item instead, and it must be not-done. Errors when "
        "there is no open item. Rewording does not make it a different task, so the item keeps "
        "its objid and every permalink to it stays valid. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-replace arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Replace the addressed (default cursor) task's summary."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        index = resolve_workitem_index(todo, self.target, what="replace")
        require_open_workitem(todo, index)
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        # PATCH the node; never delete-and-recreate it. A reworded step is the
        # SAME step, so everything that is its identity rather than its content
        # survives -- the objid above all, since re-minting one silently at the
        # next write would break every permalink already handed out for this
        # item, but also any execution hints the plan attached to it.
        item = items[index]
        item["kind"] = WORKITEM_TASK
        item["summary"] = self.summary
        item["done"] = False
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): replace work item: {_summary_snippet(self.summary)}")
        print(json.dumps({"index": index, "summary": self.summary}, indent=2))
        return 0


class WorkItemDeleteCommand(WorkItemEditCommand):
    command_names = ("work-item-delete",)
    doc_short: ClassVar[str] = "Delete a not-done work item"
    doc_long: ClassVar[str] = (
        "Work-item-delete removes a not-done item: the cursor by default, or the one an explicit "
        "TARGET names (an index, negative counting from the end, or objid:<hex>) -- dropping a "
        "step further down the plan without having to work forward to it. Done items are the "
        "history of the todo, so a target that names one is an error, not a deletion. Deleting "
        "drops the step AND the fact that it was ever planned, so once a plan is real prefer "
        "work-item-obsolete, which closes a no-longer-wanted step and keeps the reason in the "
        "trail. Errors when there is no open item. The write is store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-delete arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Delete the addressed (default cursor) work item."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        index = resolve_workitem_index(todo, self.target, what="delete")
        require_open_workitem(todo, index)
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


class WorkItemReorderCommand(WorkItemEditCommand):
    command_names = ("work-item-reorder",)
    doc_short: ClassVar[str] = "Move a not-done item in the plan"
    doc_long: ClassVar[str] = (
        "Work-item-reorder moves ONE not-done item to another position in the plan, leaving every "
        "other item in its existing relative order. SRC names the item to move: an index (0-based, "
        "negative counting from the end) or objid:<hex>. DST is a POSITION -- the index the item "
        "should occupy afterwards -- negative counting from the end the way python indexing does, "
        "so -1 is last and -2 next-to-last; objid:<hex> is a SRC form and is rejected for DST. "
        "Because a move never changes the list's length, 'the end' is unambiguous: DST -1 always "
        "means last. The done prefix is immovable and out of bounds at both ends (invariant #3): "
        "SRC must be a not-done item, and DST cannot land above the cursor. Moving an item to the "
        "position it already holds is a no-op. Use it to put a plan whose steps came out in the "
        "wrong dependency order into topological order, or to push a stalled step to the end so "
        "the rest can proceed -- which is NOT work-item-done --blocked, the completion for a step "
        "that cannot be done at all. Address by objid when making several moves: each move "
        "renumbers the items after it, while an objid keeps naming the same item. The write is "
        "store-only."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-reorder arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument(
            "src",
            help=(
                "item to move: an index (0-based; negative counts from the end) or "
                f"{WORKITEM_OBJID_SCHEME}<hex>. Must be a not-done item"
            ),
        )
        parser.add_argument(
            "dst",
            help=(
                "index the item should occupy afterwards; negative counts from the end "
                "(-1 is last). Cannot land in the done prefix"
            ),
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Move one not-done work item to another position in the plan."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        frontier = cursor_index(todo)
        if frontier is None:
            raise TodoError(
                "this todo has no not-done work items; there is nothing reorderable "
                "(done items are its history -- invariant #3)"
            )
        src = resolve_workitem_index(todo, self.src, what="reorder")
        require_open_workitem(todo, src)
        if self.dst.startswith(WORKITEM_OBJID_SCHEME):
            # DST is a slot, not an item. "Before or after that item?" has no
            # answer once SRC has been lifted out, so the ambiguity is refused
            # rather than guessed at.
            raise TodoError(
                f"DST is a position, not an item: pass an index (negative counts from the "
                f"end). {WORKITEM_OBJID_SCHEME}<hex> addresses SRC"
            )
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        dst = _workitem_index_by_number(items, self.dst)
        if dst < frontier:
            raise TodoError(
                f"work item {self.dst} is in the done prefix (items 0..{frontier - 1}); a "
                "not-done item cannot move above the cursor (invariant #3)"
            )
        # Pop then insert at DST. The list keeps its length, so the item lands
        # exactly at index DST -- which is what makes a negative DST mean the
        # position it names (-1 is last) rather than python's insert-before.
        items.insert(dst, items.pop(src))
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        node = todo["WorkItems"][dst]
        summary = str(node.get("summary", ""))
        if not self.no_commit:
            commit_todo(root, f"chore(todo): reorder work item: {_summary_snippet(summary)}")
        print(
            json.dumps(
                {
                    "from_index": src,
                    "to_index": dst,
                    "objid": node.get(todo_objid.OBJID_KEY, ""),
                    "summary": summary,
                },
                indent=2,
            )
        )
        return 0


class WorkItemCheckpointCommand(WorkItemProgressCommand):
    command_names = ("work-item-checkpoint",)
    doc_short: ClassVar[str] = "Close an item that finished with no commit"
    doc_long: ClassVar[str] = (
        "Work-item-checkpoint closes a not-done item that FINISHED but produced no commit -- "
        "recon whose findings went into Body, a wait, bookkeeping -- as kind=checkpoint. It "
        "records branch HEAD as at_sha, which is OBSERVATIONAL (where the step finished) and "
        "never attribution: a checkpoint claims no authorship of that commit, unlike the `sha` "
        "work-item-done records. So it needs the todo's branch checked out to read HEAD, and a "
        "clean tree, since a dirty one means real work is about to be stranded (commit it with "
        "plain work-item-done instead). -m says what the no-code step actually did; without it "
        "the item records an explicit no-op rather than inheriting HEAD's commit message. TARGET "
        "is an index (negative counts from the end) or objid:<hex>, defaulting to the cursor. "
        "The item is patched in place, so it keeps its objid, and it moves to the end of the done "
        "prefix (invariant #3). Was work-item-done --checkpoint."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-checkpoint arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument(
            "-m",
            "--message",
            help="what the no-commit step did; defaults to an explicit no-op marker",
        )
        parser.add_argument("--summary", help="override the work item's high-level description")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Close the addressed (default cursor) item as a no-commit checkpoint."""
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        # at_sha comes from git, so unlike its two siblings this one needs the
        # todo's own branch checked out -- a checkpoint against some other
        # branch's HEAD would record a position the trail cannot use.
        branch = str(todo.get("Branch") or "")
        checked_out = current_branch(root)
        if checked_out != branch:
            raise TodoError(
                f"work-item-checkpoint records HEAD of the todo's branch {branch!r}; "
                f"run it from a checkout of that branch (currently on {checked_out!r})"
            )
        if run_git(root, "status", "--porcelain", check=False).stdout.strip():
            raise TodoError(
                "work-item-checkpoint records no commit but the tree is dirty; commit the work "
                "(plain work-item-done) or clean the tree first"
            )
        head = head_sha(root)
        if not head:
            raise TodoError("no commits on branch; cannot record a checkpoint position")
        index = resolve_workitem_index(todo, self.target, what="checkpoint")
        require_open_workitem(todo, index)
        landed = close_workitem(
            todo,
            index,
            WORKITEM_CHECKPOINT,
            message=self.message or NOOP_CHECKPOINT_MESSAGE,
            summary=self.summary or "",
            extra={"at_sha": str(head)},
        )
        write_todo_worktree(root, todo)
        payload = closed_workitem_payload(todo, landed, from_index=index)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): checkpoint work item: {_summary_snippet(payload['summary'])}")
        print(json.dumps(payload, indent=2))
        return 0


class WorkItemBlockedCommand(WorkItemProgressCommand):
    command_names = ("work-item-blocked",)
    doc_short: ClassVar[str] = "Close an item that cannot be done as written"
    doc_long: ClassVar[str] = (
        "Work-item-blocked closes a not-done item that is still OWED but cannot be done AS "
        "WRITTEN -- the approach turned out to be impossible, or the data it needs does not "
        "exist -- as kind=blocked. -m is required and is the item's entire content: the LONG form "
        "of what was tried, what was actually found (concrete: fixture names, ids, counts, error "
        "types), why the approach cannot work, and the options as you see them. The State note is "
        "read once by the user deciding what happens next; the WorkItems trail is what a future "
        "agent walks, so the narrative has to live here. Store-only -- it needs no branch "
        "checkout and no clean tree, because nothing it records comes from git (contrast "
        "work-item-checkpoint, which reads HEAD). TARGET is an index (negative counts from the "
        "end) or objid:<hex>, defaulting to the cursor. The item is patched in place, so it keeps "
        "its objid and the permalink you hand the user in the userneeded note stays valid, and it "
        "moves to the end of the done prefix (invariant #3). Doctor rejects a blocked LAST item "
        "of a done todo (#6): that is the tool refusing to call a todo finished when its final "
        "act was failing to do something. Was work-item-done --blocked, which recorded kind=code "
        "with a sentinel sha; the kind now says it instead."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-blocked arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument(
            "-m",
            "--message",
            required=True,
            help=(
                "the long form: what was tried, what was found, why the approach cannot work, "
                "and the options"
            ),
        )
        parser.add_argument("--summary", help="override the work item's high-level description")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Close the addressed (default cursor) item as blocked."""
        if not self.message.strip():
            raise TodoError(
                "-m must carry the long form: what was tried, what was found, and what the "
                "options are -- a bare 'blocked' teaches the next agent nothing"
            )
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        index = resolve_workitem_index(todo, self.target, what="mark blocked")
        require_open_workitem(todo, index)
        landed = close_workitem(
            todo, index, WORKITEM_BLOCKED, message=self.message, summary=self.summary or ""
        )
        write_todo_worktree(root, todo)
        payload = closed_workitem_payload(todo, landed, from_index=index)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): blocked work item: {_summary_snippet(payload['summary'])}")
        print(json.dumps(payload, indent=2))
        return 0


class WorkItemObsoleteCommand(WorkItemProgressCommand):
    command_names = ("work-item-obsolete",)
    doc_short: ClassVar[str] = "Close an item as no longer wanted"
    doc_long: ClassVar[str] = (
        "Work-item-obsolete closes a not-done item that is no longer WANTED -- descoped, "
        "superseded, or subsumed by another step -- as kind=obsolete carrying the required -m "
        "reason. Three things can end a step, and they say different things: work-item-done "
        "COMPLETED it; work-item-done --blocked still owes it (it cannot be done AS WRITTEN, so "
        "someone has to decide what happens next); obsolete owes it nothing. Prefer it over "
        "work-item-delete once a plan is real -- delete erases the step and its reason, obsolete "
        "keeps both in the trail a later reader walks. TARGET is an index (negative counts from "
        "the end) or objid:<hex>, defaulting to the cursor, because a step usually turns out to "
        "be unnecessary while an earlier one is still current. The item is PATCHED in place, so "
        "it keeps its objid and any permalink to it stays valid, and it moves to the end of the "
        "done prefix -- it is history now, not plan -- which is what keeps done items a prefix "
        "(invariant #3). Store-only: it makes no commit and needs no branch checkout. Doctor "
        "rejects an obsolete item as the LAST item of a done todo (#6, as for --blocked): a todo "
        "whose final act was dropping a step has stopped, not finished."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-obsolete arguments."""
        parser.add_argument("selector", help="todo selector: Id prefix (4+ hex) or full digest")
        parser.add_argument("target", nargs="?", help=WORKITEM_TARGET_HELP)
        parser.add_argument(
            "-m",
            "--message",
            required=True,
            help=(
                "why the step is no longer wanted: descoped by whom, superseded by what, or "
                "which other step subsumed it"
            ),
        )
        parser.add_argument("--summary", help="override the work item's high-level description")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Close the addressed (default cursor) work item as no longer wanted."""
        if not self.message.strip():
            raise TodoError(
                "-m must say why the step is no longer wanted; that reason is the entire "
                "content of an obsolete item, and a blank one records nothing"
            )
        root = self.root()
        _, todo = resolve_ticket_by_id(root, self.selector)
        normalize_todo_schema(todo)
        index = resolve_workitem_index(todo, self.target, what="mark obsolete")
        require_open_workitem(todo, index)
        landed = close_workitem(
            todo, index, WORKITEM_OBSOLETE, message=self.message, summary=self.summary or ""
        )
        write_todo_worktree(root, todo)
        payload = closed_workitem_payload(todo, landed, from_index=index)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): obsolete work item: {_summary_snippet(payload['summary'])}")
        print(json.dumps(payload, indent=2))
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

    It also reconciles derived ``mention`` relations against each relto-bearing
    node's own prose (see ``sync_mentions``), persisting them before the audit
    so a mention derived this run is audited this run.
    """
    _loc, todo = resolve_ticket_by_id(root, selector)
    # Derive mentions FIRST, and persist them before auditing, so a mention
    # this run derives is audited by this same run rather than the next one --
    # a target the prose names but the record lacks is reported immediately.
    mentions = sync_mentions(todo)
    if mentions and not dry_run:
        write_todo_worktree(root, todo)
    findings = doctor_findings(root, selector)
    warnings = doctor_warnings(root, selector)
    repairs = reestablish_backlinks(root, todo, dry_run=dry_run)
    repairs.extend(f"would {change}" if dry_run else change for change in mentions)
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
        "mentions": len(mentions),
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
        "reported as 'auto_tags'. It reconciles derived relto 'mention' entries against each "
        "relto-bearing node's own editable prose -- Body.raw, a note's raw, a work item's "
        "summary -- adding one for a target the prose names and dropping one for a target it no "
        "longer names, while never touching an entry of any other type; reported as 'mentions'. "
        "A work item's git-copied message is not scanned. For a ROOT todo in a terminal state it reconciles the PR "
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
                        "mentions": sum(r["mentions"] for r in results),
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
                    "mentions": result["mentions"],
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
    cmd = ["log", f"--format={fmt}"]
    env = None
    if timestamps:
        # UTC, to match the node's stored update_dt (RFC3339 Z) -- no mixed zones.
        cmd.append("--date=format-local:%Y-%m-%d %H:%M")
        env = {**os.environ, "TZ": "UTC0"}
    cmd.append(f"{base}..{branch}")
    result = git_command.get_git().run(repo, *cmd, env=env)
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


# The options `web` hands on to todoweb.py; todoweb defines what they mean.
WEB_LEVELS = ("none", "read", "write")
WEB_DEFAULT_PORT = 8765
TODOWEB_PY = Path(__file__).resolve().with_name("todoweb.py")


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
        "lexical search (the same ranking as 'todo search') over every todo, showing update-time "
        "and State columns, with an empty query listing all. It also serves permalinks: "
        "/<todoid>/<path...> renders the whole todo focused on the object that path resolves to "
        "(see 'resolveurl' for the grammar). Access is set per client class, each none, read or "
        "write: --loopback for clients whose source address is loopback (default read) and "
        "--public for every other client (default none). none answers 403 to every request, "
        "read serves GET only, write also lets the todo page edit the CLI's update surface: "
        "Edit on Summary, Body, LongSummary, AC, ActualSummary, each note and each not-done "
        "work item, and Up/Down on not-done work items, each saved through the matching set / "
        "note-replace / work-item-replace / work-item-reorder command. Nothing is created or "
        "deleted. Saves are last-write-wins: a save lands even when the todo changed since the "
        "page loaded. Both none refuses to start. The default bind is localhost when public is "
        "none and '::' (every interface) otherwise; --host overrides. Every web option "
        "defaults from the \"web\" object of the todo dir's config.json (CLI beats config "
        "beats built-in). Writes are refused unless the request's Origin, content type and "
        "(from loopback clients) Host are this viewer's own (see IMPLEMENTATION.md, 'Web edits')."
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
        parser.add_argument(
            "--host",
            default=None,
            help="bind host (default 'localhost' when --public is none, else "
            "'::', which serves IPv4 and IPv6)",
        )
        parser.add_argument(
            "--port", type=int, default=None, help=f"bind port (default {WEB_DEFAULT_PORT})"
        )
        parser.add_argument(
            "--loopback",
            choices=WEB_LEVELS,
            default=None,
            help="access for loopback clients (default read; config.json web.loopback)",
        )
        parser.add_argument(
            "--public",
            choices=WEB_LEVELS,
            default=None,
            help="access for every other client (default none; config.json web.public)",
        )
        parser.add_argument(
            "--dump-html",
            action="store_true",
            help="print the rendered HTML and exit instead of starting a server",
        )

    def todoweb_argv(self) -> List[str]:
        """The todoweb.py arguments that carry this command's own options."""
        argv: List[str] = []
        for flag, value in (
            ("--host", self.host),
            ("--port", self.port),
            ("--loopback", self.loopback),
            ("--public", self.public),
        ):
            if value is not None:
                argv += [flag, str(value)]
        if self.dump_html:
            argv.append("--dump-html")
        if self.selector is not None:
            argv += ["--", self.selector]
        return argv

    def do(self) -> int:
        """Run todoweb.py with these options; its exit status is this command's."""
        return subprocess.run(
            [sys.executable, str(TODOWEB_PY), *self.todoweb_argv()], check=False
        ).returncode


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


class SearchCommand(CorpusQueryCommand):
    command_names = ("search",)
    doc_short: ClassVar[str] = "Search todos (lexical IDF)"
    doc_long: ClassVar[str] = (
        "Search ranks todos in the resolved todo directory ($TODO_DIR, then the "
        ".todo walk -- the same store as ls) by reciprocal-rank fusion over one or "
        "more embedders plus lexical overlap. The current directory does not need "
        "to be a git repo. Multiple text terms are searched google-style (OR): "
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
        "(default: the store's 'embedder' config; absent or null means none). A "
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
            help="comma list of embedders (default: the store's 'embedder' config, else none)",
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
        """Print ranked ticket search hits from the resolved todo directory."""
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
        "down to WHAT before starting. Each record's Body is followed by every "
        "note reachable from its Body.relto -- transitively, within that record "
        "only -- each under its own 'note [objid:...]' header; a relto target "
        "naming anything but a note (a work item, a subtodo, ...) emits nothing, "
        "and a todo: or cross-todo target is never chased, printing a one-line "
        "'[not followed: ...]' pointer instead. De-duplication (shared ancestors "
        "and shared notes alike) spans the whole chain. Read-only: it resolves "
        "parents from the db without checking out branches. Selector is a 4+ hex "
        "Id prefix or the full digest."
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
        "current worktree, so all worktrees of a repo share one store. The winning "
        "directory's own config.json may then redirect elsewhere via a todo_dir key "
        "(relative or absolute; chains follow; a cycle is a hard error) -- basedir "
        "prints the final, post-redirect directory."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Basedir takes no arguments."""

    def do(self) -> int:
        """Print the resolved todo base directory."""
        print(self.todo_dir)
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
        base = Path(self.basedir) if self.basedir else self.todo_dir
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
                lines.append(f"  {name:<20} {leaf.doc_short}")
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
               That directory's own config.json may redirect elsewhere via a
               todo_dir key (relative to config.json's dir, or absolute; chains
               follow; a cycle is a hard error) -- the redirect target is what
               actually gets used.
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


def command_class_selected(command_cls: type, names: Sequence[str]) -> bool:
    """True when *names* cites *command_cls* or one of its TodoSubCommand bases.

    Comparison is case-insensitive and limited to the subcommand hierarchy, so
    ``object`` or ``ABC`` never select every command. An empty list selects nothing.
    """
    wanted = {name.strip().casefold() for name in names if name.strip()}
    if not wanted:
        return False
    for cls in command_cls.__mro__:
        if not isinstance(cls, type) or not issubclass(cls, TodoSubCommand):
            continue
        if cls.__name__.casefold() in wanted:
            return True
    return False


def _autocommit_message(command: TodoSubCommand, paths: Sequence[Path]) -> str:
    """One-line commit subject: the CLI name plus the short ids that changed."""
    name = command.command_names[0] if command.command_names else type(command).__name__
    ids = _ticket_ids_in_paths(paths)
    return f"todo: {name}" + (f" {' '.join(ids)}" if ids else "")


def sync_file_store_git(command: TodoSubCommand) -> None:
    """Commit and/or push after a file-store write selected by config.json.

    ``autocommit`` and ``autopush`` are lists of subcommand class names. The
    running command matches when its class, or any TodoSubCommand base, is named
    (case-insensitive). Sqlite ignores both lists. A command that wrote no store
    file -- a read, including one selected via a parent class -- does nothing.
    """
    base = command.todo_dir
    commit_names = todo_store.config_list(base, AUTOCOMMIT_KEY)
    push_names = todo_store.config_list(base, AUTOPUSH_KEY)
    if not commit_names and not push_names:
        return
    command_cls = type(command)
    do_commit = command_class_selected(command_cls, commit_names)
    do_push = command_class_selected(command_cls, push_names)
    if not do_commit and not do_push:
        return
    store = todo_store.get_store()
    if not isinstance(store, todo_store.JsonDirTodoStore):
        return
    paths = store.written_paths()
    if not paths:
        return
    root = repo_root(store.dir)
    if do_commit:
        _commit_store_paths(root, paths, _autocommit_message(command, paths))
    if do_push:
        _autopush(root)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)
    logged_argv: List[str] = list(argv) if argv is not None else sys.argv[1:]
    command_name: str = getattr(args, "command", "") or ""
    start: float = time.monotonic()
    exit_code: int = 1
    # A long-lived process (web) runs many commands against one cached store.
    todo_store.discard_written_paths()
    try:
        # Every subcommand reads the store. Resolve once here so library code
        # (todo_db.todo_dir cache) and the command (self.todo_dir) share one path.
        resolved_todo_dir = todo_db.resolve_todo_dir()
        _warn_if_store_behind()
        _warn_if_skills_buried()
        command: TodoSubCommand = args.command_cls(args, todo_dir=resolved_todo_dir)
        exit_code = int(command.do())
        if exit_code == 0:
            sync_file_store_git(command)
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

"""Web viewer for todo tickets: a labeled representation with a movable split.

Above the split: the todo itself -- Id, Parent (horizontal boxes), Summary,
Body, Work items (horizontal boxes), Subtodos (horizontal boxes). Every box has
one click model: clicking the box opens the target in the fold below (a work
item shows its commit message + diff; a subtodo or parent shows a read-only
rendition), and clicking the box's underlined id/sha is a plain hyperlink (same
window, or a new tab on cmd/ctrl/middle-click) that navigates to that todo's
page (subtodo/parent) or the github commit (work item). A work-item box also
highlights any subtodo it references, and a subtodo box highlights the work
items that reference it.

Opened with an ``?id=`` query the viewer shows that todo; opened bare it shows a
search box over every discoverable todo (empty query lists them all). All
below-fold content is pre-computed and embedded in the page, so a dumped page is
a complete self-contained artifact.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

JsonDict = Dict[str, Any]

_DONE_KINDS = frozenset({"code", "merge_subtodo", "start_subtodo"})

_DEBUG_COUNTER: int = 0


def _debug_enabled() -> bool:
    """Return True when verbose todo web tracing is enabled."""
    return bool(os.environ.get("TODO_WEB_DEBUG"))


def _debug(message: str, *, phase: str = "todo_web") -> None:
    """Emit a stderr trace line when TODO_WEB_DEBUG is set."""
    if not _debug_enabled():
        return
    global _DEBUG_COUNTER
    _DEBUG_COUNTER += 1
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    print(f"todo_web[{stamp}] #{_DEBUG_COUNTER} {phase}: {message}", file=sys.stderr, flush=True)


class TodoWebError(Exception):
    """User-facing web viewer error."""


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in *root* and return the completed process."""
    cmd = "git " + " ".join(args)
    started = time.monotonic()
    _debug(f"start {cmd} cwd={root}")
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    _debug(f"done {cmd} rc={result.returncode} elapsed_ms={elapsed_ms}", phase="git")
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _debug(f"git failed: {detail}", phase="git.error")
        raise TodoWebError(f"git {' '.join(args)} failed: {detail}")
    return result


def normalize_todo(todo: JsonDict) -> JsonDict:
    """Normalize legacy todo fields for rendering."""
    if "Chunks" in todo and "WorkItems" not in todo:
        todo["WorkItems"] = todo.pop("Chunks")
    if "Subtickets" in todo and "Subtodos" not in todo:
        todo["Subtodos"] = todo.pop("Subtickets")
    return todo


def current_state_name(todo: JsonDict) -> Optional[str]:
    """Return the single State key, if present."""
    state = todo.get("State")
    if isinstance(state, str):
        return state or None
    if not isinstance(state, dict) or len(state) != 1:
        return None
    return next(iter(state.keys()))


def read_todo_at_ref(root: Path, ref: str) -> Optional[JsonDict]:
    """Read TODO.json at *ref*, returning None when absent or invalid."""
    _debug(f"read_todo_at_ref ref={ref!r}")
    result = run_git(root, "show", f"{ref}:TODO.json", check=False)
    if result.returncode != 0:
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo(parsed)


def github_repo_url(remote_url: Optional[str]) -> Optional[str]:
    """Predict a GitHub web URL from common origin URL shapes."""
    if not remote_url:
        return None
    patterns = (
        r"\Ahttps://github\.com/(?P<path>[^/]+/[^/]+?)(?:\.git)?/?\Z",
        r"\Agit@github\.com:(?P<path>[^/]+/[^/]+?)(?:\.git)?\Z",
        r"\Assh://git@github\.com/(?P<path>[^/]+/[^/]+?)(?:\.git)?/?\Z",
    )
    for pattern in patterns:
        match = re.match(pattern, remote_url)
        if match:
            return f"https://github.com/{match.group('path').removesuffix('.git')}"
    return None


def repo_origin(root: Path) -> Optional[str]:
    """Return origin URL when configured."""
    result = run_git(root, "remote", "get-url", "origin", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def load_child_ticket(root: Path, entry: JsonDict) -> JsonDict:
    """Load a child ticket from its branch, or fall back to the Subtodos snapshot."""
    entry_id = str(entry.get("Id") or "")
    branch = str(entry.get("Branch") or "")
    if branch:
        child = read_todo_at_ref(root, branch)
        if child is not None and str(child.get("Id") or "") == entry_id:
            return child
    return {
        "Id": entry_id,
        "Branch": branch,
        "Summary": {"raw": entry.get("Summary", "")},
        "State": {str(entry.get("State", "init")): {}},
        "WorkItems": [],
        "Subtodos": [],
    }


def commit_message(root: Path, commit_hash: str) -> str:
    """Return the full commit message (subject + body) for one commit."""
    result = run_git(root, "show", "-s", "--format=%B", commit_hash, check=False)
    if result.returncode != 0:
        return "[commit message unavailable]\n"
    return result.stdout


def diff_unified(root: Path, commit_hash: str) -> str:
    """Return a unified patch for one commit."""
    result = run_git(
        root, "show", "--format=", "--patch", "--find-renames", commit_hash, check=False
    )
    if result.returncode != 0:
        return "[diff unavailable]\n"
    return result.stdout


# --- todo field extraction -------------------------------------------------


def _raw_field(todo: JsonDict, key: str) -> str:
    """Return the ``.raw`` text of a Summary/Body-shaped field, tolerating strings."""
    value = todo.get(key)
    if isinstance(value, dict):
        return str(value.get("raw") or "")
    return str(value or "")


def _summary_text(todo: JsonDict) -> str:
    return _raw_field(todo, "Summary")


def _body_text(todo: JsonDict) -> str:
    return _raw_field(todo, "Body")


def _state_text(todo: JsonDict) -> str:
    return current_state_name(todo) or "?"


def _workitems_view(todo: JsonDict) -> List[JsonDict]:
    """Light per-work-item dicts for box rendering (no git reads)."""
    out: List[JsonDict] = []
    items = todo.get("WorkItems") or []
    if not isinstance(items, list):
        return out
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or ("code" if item.get("done") else "task"))
        sha = item.get("sha")
        sha = sha if isinstance(sha, str) and sha else ""
        done = bool(item.get("done")) or kind in _DONE_KINDS
        out.append(
            {
                "idx": idx,
                "kind": kind,
                "summary": str(item.get("summary") or ""),
                "done": done,
                "sha": sha,
                "short": sha[:8] if sha else "",
                "subtodo": str(item.get("subtodo_id") or ""),
            }
        )
    return out


def _subtodos_view(root: Path, todo: JsonDict) -> List[JsonDict]:
    """Light per-subtodo dicts, each carrying the loaded child for read-only render."""
    out: List[JsonDict] = []
    for entry in todo.get("Subtodos") or []:
        if not isinstance(entry, dict):
            continue
        child = normalize_todo(load_child_ticket(root, entry))
        cid = str(child.get("Id") or entry.get("Id") or "")
        out.append(
            {
                "id": cid,
                "short": cid[:8],
                "summary": _summary_text(child) or str(entry.get("Summary") or ""),
                "state": _state_text(child),
                "child": child,
            }
        )
    return out


# --- HTML rendering --------------------------------------------------------


def _wi_box(item: JsonDict, *, interactive: bool, github: str = "") -> str:
    """Render one work-item box: the box opens the commit message/diff in the
    fold. Any git sha is shown as ``sha:<short>`` (a github hyperlink on
    interactive boxes) and any referenced subtodo as ``todo:<short>`` (a
    hyperlink to that todo's page) -- start_subtodo carries only the todo,
    merge_subtodo carries both, so the labels keep the two hex ids apart.

    *github* is the repo web URL base (empty when unknown); the sha link is only
    rendered on interactive boxes that carry both a sha and a known github URL.
    """
    classes = ["wi"]
    if not interactive:
        classes.append("static")
    if item["done"]:
        classes.append("done")
    attrs = ""
    if interactive:
        attrs = f' data-idx="{item["idx"]}" data-subtodo="{html.escape(item["subtodo"])}"'
    if not item["subtodo"]:
        todo_html = ""
    elif interactive:
        todo_html = (
            f'<a class="wi-sub mono idlink" href="/?id={html.escape(item["subtodo"])}">'
            f'todo:{html.escape(item["subtodo"][:8])}</a>'
        )
    else:
        todo_html = f'<div class="wi-sub mono">todo:{html.escape(item["subtodo"][:8])}</div>'
    if not item["short"]:
        sha_html = ""
    elif interactive and github and item["sha"]:
        href = f'{html.escape(github)}/commit/{html.escape(item["sha"])}'
        sha_html = f'<a class="wi-sha idlink" href="{href}">sha:{html.escape(item["short"])}</a>'
    else:
        sha_html = f'<div class="wi-sha">sha:{html.escape(item["short"])}</div>'
    # merge_subtodo carries both; the inline anchors would otherwise abut.
    sep = "&nbsp;&nbsp;" if todo_html and sha_html else ""
    mark = "[x]" if item["done"] else "[ ]"
    return (
        f'<div class="{" ".join(classes)}"{attrs}>'
        f'<div class="wi-kind">{mark} {html.escape(item["kind"])}</div>'
        f'<div class="wi-sum">{html.escape(item["summary"] or "(no summary)")}</div>'
        f"{todo_html}{sep}{sha_html}"
        "</div>"
    )


def _st_box(sub: JsonDict, *, interactive: bool) -> str:
    """Render one subtodo box: the box opens the subtodo in the fold, the
    underlined id is a plain hyperlink to that todo's own page."""
    classes = ["st"] if interactive else ["st", "static"]
    if interactive:
        attrs = f' data-st="{html.escape(sub["id"])}"'
        id_html = (
            f'<a class="st-id mono idlink" href="/?id={html.escape(sub["id"])}">'
            f'todo:{html.escape(sub["short"] or "?")}</a>'
        )
    else:
        attrs = ""
        id_html = f'<div class="st-id mono">todo:{html.escape(sub["short"] or "?")}</div>'
    return (
        f'<div class="{" ".join(classes)}"{attrs}>'
        f"{id_html}"
        f'<div class="st-sum">{html.escape(sub["summary"] or "(no summary)")}</div>'
        f'<div class="st-state">{html.escape(sub["state"])}</div>'
        "</div>"
    )


def _parents_view(root: Path, todo: JsonDict) -> List[JsonDict]:
    """Per-parent dicts from the Parent field (a list of {Id, Branch}), each
    carrying the loaded parent so the fold can show a read-only repr."""
    out: List[JsonDict] = []
    parents = todo.get("Parent")
    if isinstance(parents, dict):  # tolerate legacy single-parent shape
        parents = [parents]
    if not isinstance(parents, list):
        return out
    for entry in parents:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("Id") or "")
        if not pid:
            continue
        child = normalize_todo(load_child_ticket(root, entry))
        out.append(
            {
                "id": pid,
                "short": pid[:8],
                "branch": str(entry.get("Branch") or ""),
                "summary": _summary_text(child) or str(entry.get("Summary") or ""),
                "state": _state_text(child),
                "child": child,
            }
        )
    return out


def _parent_box(p: JsonDict, *, interactive: bool) -> str:
    """Render one parent box, mirroring a subtodo box: the box opens the parent
    in the fold, the underlined id is a plain hyperlink to that todo's page."""
    classes = ["st"] if interactive else ["st", "static"]
    if interactive:
        attrs = f' data-parent="{html.escape(p["id"])}"'
        id_html = (
            f'<a class="st-id mono idlink" href="/?id={html.escape(p["id"])}">'
            f'todo:{html.escape(p["short"] or "?")}</a>'
        )
    else:
        attrs = ""
        id_html = f'<div class="st-id mono">todo:{html.escape(p["short"] or "?")}</div>'
    branch = f'<div class="st-state">{html.escape(p["branch"])}</div>' if p["branch"] else ""
    return (
        f'<div class="{" ".join(classes)}"{attrs}>'
        f"{id_html}"
        f'<div class="st-sum">{html.escape(p["summary"] or "(no summary)")}</div>'
        f'<div class="st-state">{html.escape(p["state"])}</div>'
        f"{branch}"
        "</div>"
    )


def _parents_html(parents: List[JsonDict], *, interactive: bool) -> str:
    """Render the Parent section as boxes (same click model as subtodos)."""
    if not parents:
        return ""
    boxes = "".join(_parent_box(p, interactive=interactive) for p in parents)
    return (
        f'<section class="part"><h2>Parent</h2>'
        f'<div class="row">{boxes}</div></section>'
    )


# Top-level fields with their own rich rendering above; everything else is
# surfaced generically by _meta_html. Embedding vectors are not top-level (they
# live inside Summary/Body as .hash and only .raw is rendered), so nothing
# opaque reaches the generic path.
_DEDICATED_FIELDS = frozenset(
    {"Id", "Summary", "Body", "Parent", "WorkItems", "Subtodos", "State"}
)


def _meta_html(todo: JsonDict) -> str:
    """Render remaining non-opaque top-level fields (Branch, create/update time,
    AC, Scope, and any future field) as labeled rows -- one source of truth for
    'show everything the todo carries'."""
    rows: List[str] = []
    for key, value in todo.items():
        if key in _DEDICATED_FIELDS:
            continue
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            rendered = f'<pre class="val body">{html.escape(json.dumps(value, indent=2, sort_keys=True))}</pre>'
        else:
            rendered = f'<div class="val">{html.escape(str(value))}</div>'
        rows.append(f'<h3 class="meta-key">{html.escape(str(key))}</h3>{rendered}')
    if not rows:
        return ""
    return f'<section class="part"><h2>Fields</h2>{"".join(rows)}</section>'


def _sections_html(
    todo: JsonDict,
    witems: List[JsonDict],
    stodos: List[JsonDict],
    parents: List[JsonDict],
    *,
    interactive: bool,
    github: str = "",
) -> str:
    """Render the labeled todo representation: Id, Parent, Summary, Body, work
    items, subtodos, and remaining non-opaque fields."""
    tid = str(todo.get("Id") or "")
    summary = _summary_text(todo)
    body = _body_text(todo)
    parents_html = _parents_html(parents, interactive=interactive)
    wi_boxes = "".join(_wi_box(w, interactive=interactive, github=github) for w in witems)
    st_boxes = "".join(_st_box(s, interactive=interactive) for s in stodos)
    wi_row = f'<div class="row">{wi_boxes}</div>' if wi_boxes else '<div class="none">none</div>'
    st_row = f'<div class="row">{st_boxes}</div>' if st_boxes else '<div class="none">none</div>'
    return (
        f'<section class="part"><h2>Id</h2>'
        f'<div class="val mono">{html.escape(tid or "?")}</div>'
        f' <span class="state-tag">{html.escape(_state_text(todo))}</span></section>'
        f"{parents_html}"
        f'<section class="part"><h2>Summary</h2>'
        f'<div class="val">{html.escape(summary or "(no summary)")}</div></section>'
        f'<section class="part"><h2>Body</h2>'
        f'<pre class="val body">{html.escape(body)}</pre></section>'
        f"<section class=\"part\"><h2>Work items</h2>{wi_row}</section>"
        f"<section class=\"part\"><h2>Subtodos</h2>{st_row}</section>"
        f"{_meta_html(todo)}"
    )


def _static_repr_html(root: Path, child: JsonDict, github: str = "") -> str:
    """Read-only rendition of a subtodo/parent, mirroring the layout, no links."""
    child = normalize_todo(child)
    witems = _workitems_view(child)
    stodos = _subtodos_view(root, child)
    parents = _parents_view(root, child)
    return (
        '<div class="static-repr">'
        f"{_sections_html(child, witems, stodos, parents, interactive=False, github=github)}"
        "</div>"
    )


def _page_data(
    root: Path,
    todo: JsonDict,
    witems: List[JsonDict],
    stodos: List[JsonDict],
    parents: List[JsonDict],
    github: Optional[str],
) -> JsonDict:
    """Assemble the embedded JSON: per-work-item message/diff and per-subtodo /
    per-parent repr HTML."""
    github = github or ""
    data: JsonDict = {
        "id": str(todo.get("Id") or ""),
        "workitems": [],
        "subtodos": {},
        "parents": {},
    }
    for w in witems:
        sha = w["sha"]
        data["workitems"].append(
            {
                "idx": w["idx"],
                "kind": w["kind"],
                "short": w["short"],
                "subtodo": w["subtodo"],
                "message": commit_message(root, sha) if sha else "",
                "diff": diff_unified(root, sha) if sha else "",
                "github": f"{github}/commit/{sha}" if github and sha else "",
            }
        )
    for s in stodos:
        data["subtodos"][s["id"]] = {"reprHtml": _static_repr_html(root, s["child"], github)}
    for p in parents:
        data["parents"][p["id"]] = {"reprHtml": _static_repr_html(root, p["child"], github)}
    return data


def _embed_json(data: JsonDict) -> str:
    """Serialize *data* for safe inlining inside a <script> element."""
    return (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


_STYLE = """<style>
  html, body { height: 100%; }
  body { margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         color: #17202a; display: flex; flex-direction: column; height: 100vh; }
  a { color: #0969da; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  header { padding: 8px 16px; border-bottom: 1px solid #d8dee4; background: #f6f8fa; flex: 0 0 auto; }
  header .title { font-weight: 700; }
  header .meta { color: #57606a; font-size: 12px; overflow-wrap: anywhere; }
  #top { height: 45vh; overflow: auto; padding: 8px 16px 16px; }
  /* Search page has no fold/preview: results fill below the header and scroll here. */
  body.search #top { height: auto; flex: 1 1 auto; }
  #divider { flex: 0 0 auto; height: 7px; background: #d8dee4; cursor: row-resize; }
  #divider:hover { background: #8c959f; }
  #fold { flex: 1 1 auto; overflow: auto; padding: 12px 16px; background: #fff; }
  .part { margin: 10px 0; }
  .part h2 { margin: 0 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
             color: #57606a; }
  .part h3.meta-key { margin: 8px 0 2px; font-size: 12px; color: #57606a; font-weight: 600; }
  .val { overflow-wrap: anywhere; }
  .val.body { background: #f6f8fa; padding: 10px; border-radius: 6px; white-space: pre-wrap;
              margin: 0; max-height: 20vh; overflow: auto; }
  .state-tag { font-size: 12px; color: #57606a; }
  .none { color: #8c959f; font-size: 12px; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  .wi, .st { border: 1px solid #d8dee4; border-radius: 6px; padding: 8px; width: 200px;
             background: #fff; }
  .wi { cursor: pointer; }
  .wi.static, .st.static { cursor: default; }
  .wi.done { background: #f6f8fa; }
  .wi-kind { font-size: 11px; color: #57606a; }
  .wi-sum, .st-sum { font-weight: 600; overflow-wrap: anywhere; margin: 2px 0; }
  .wi-sha { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
            color: #0969da; }
  .wi-sub { font-size: 12px; color: #0969da; }
  .st { cursor: pointer; }
  .st-id { font-size: 12px; color: #0969da; }
  a.idlink { text-decoration: underline; cursor: pointer; }
  .st-state { font-size: 11px; color: #57606a; }
  .wi.active, .st.active { border-color: #0969da; box-shadow: 0 0 0 2px #ddf4ff; }
  .wi.hi, .st.hi { border-color: #bf8700; box-shadow: 0 0 0 2px #fff8c5; }
  .fold.split-fold { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: 100%; }
  .fold-msg pre { background: #f6f8fa; padding: 12px; border-radius: 6px; white-space: pre-wrap; }
  .diff-code { background: #0d1117; color: #e6edf3; border-radius: 6px; padding: 12px; overflow: auto; }
  .diff-code a { color: #79c0ff; }
  .fold pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  .static-repr .wi, .static-repr .st { width: 180px; }
  .hint { color: #57606a; }
  .search-box { width: 100%; padding: 8px; font-size: 15px; box-sizing: border-box;
                border: 1px solid #d8dee4; border-radius: 6px; }
  .results { list-style: none; margin: 12px 0 0; padding: 0; }
  .results li { padding: 8px; border-bottom: 1px solid #eaeef2; }
  .results .r-state { color: #57606a; font-size: 12px; }
  .results .r-utime { color: #8b949e; font-size: 12px; font-family: ui-monospace, SFMono-Regular, monospace; }
</style>"""


_TODO_SCRIPT = """<script>
const DATA = __DATA__;
const fold = document.getElementById('fold');
const topPane = document.getElementById('top');
const divider = document.getElementById('divider');

function esc(s){ return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function clearHi(){
  document.querySelectorAll('.wi,.st').forEach(function(el){ el.classList.remove('hi','active'); });
}

document.querySelectorAll('#top .wi').forEach(function(el){
  el.addEventListener('click', function(){
    clearHi(); el.classList.add('active');
    var sub = el.getAttribute('data-subtodo');
    if (sub) {
      document.querySelectorAll('#top .st[data-st="'+sub+'"]').forEach(function(s){ s.classList.add('hi'); });
    }
    var wi = DATA.workitems[parseInt(el.getAttribute('data-idx'), 10)] || {};
    var head = wi.short ? ('sha:'+esc(wi.short)) : esc(wi.kind || 'work item');
    if (wi.github) { head = '<a href="'+wi.github+'">'+head+'</a>'; }
    fold.className = 'fold split-fold';
    fold.innerHTML =
      '<div class="fold-msg"><h3>'+head+'</h3><pre><code>'+esc(wi.message || '(no commit)')+'</code></pre></div>' +
      '<div class="fold-diff diff-code"><pre><code>'+esc(wi.diff || 'no diff')+'</code></pre></div>';
  });
});

document.querySelectorAll('#top .st[data-st]').forEach(function(el){
  el.addEventListener('click', function(){
    clearHi(); el.classList.add('active');
    var id = el.getAttribute('data-st');
    document.querySelectorAll('#top .wi[data-subtodo="'+id+'"]').forEach(function(w){ w.classList.add('hi'); });
    var entry = DATA.subtodos[id];
    fold.className = 'fold';
    fold.innerHTML = entry ? entry.reprHtml : '<p class="hint">No subtodo detail.</p>';
  });
});

document.querySelectorAll('#top .st[data-parent]').forEach(function(el){
  el.addEventListener('click', function(){
    clearHi(); el.classList.add('active');
    var entry = (DATA.parents || {})[el.getAttribute('data-parent')];
    fold.className = 'fold';
    fold.innerHTML = entry ? entry.reprHtml : '<p class="hint">No parent detail.</p>';
  });
});

// Clicking the underlined id/sha is a plain hyperlink: let the browser open it
// (same window, or a new tab on cmd/ctrl/middle-click) without also swapping
// the fold via the enclosing box's click handler.
document.querySelectorAll('#top .idlink').forEach(function(a){
  a.addEventListener('click', function(e){ e.stopPropagation(); });
});

var dragging = false;
divider.addEventListener('mousedown', function(){ dragging = true; document.body.style.userSelect = 'none'; });
window.addEventListener('mousemove', function(e){
  if (!dragging) return;
  var h = e.clientY - topPane.getBoundingClientRect().top;
  if (h > 60 && h < window.innerHeight - 60) { topPane.style.height = h + 'px'; }
});
window.addEventListener('mouseup', function(){ dragging = false; document.body.style.userSelect = ''; });
</script>"""


def render_todo_page(root: Path, todo: JsonDict) -> str:
    """Render the single-todo viewer: representation on top, message/diff below."""
    todo = normalize_todo(todo)
    tid = str(todo.get("Id") or "")
    started = time.monotonic()
    _debug(f"render_todo_page id={tid[:8]}", phase="render")
    witems = _workitems_view(todo)
    stodos = _subtodos_view(root, todo)
    parents = _parents_view(root, todo)
    github = github_repo_url(repo_origin(root))
    data = _page_data(root, todo, witems, stodos, parents, github)
    top_html = _sections_html(
        todo, witems, stodos, parents, interactive=True, github=github or ""
    )
    title = html.escape(_summary_text(todo) or "todo")
    script = _TODO_SCRIPT.replace("__DATA__", _embed_json(data))
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  {_STYLE}
</head>
<body>
  <header>
    <div class="title">{title}</div>
    <div class="meta mono">todo:{html.escape(tid)} &middot; {html.escape(str(root))}</div>
  </header>
  <div id="top">{top_html}</div>
  <div id="divider"></div>
  <div id="fold" class="fold"><p class="hint">Click a work item to see its message and diff. Click a subtodo to view it. Drag the bar to resize.</p></div>
  {script}
</body>
</html>
"""
    _debug(
        f"render_todo_page exit id={tid[:8]} bytes={len(page.encode('utf-8'))} "
        f"elapsed_ms={int((time.monotonic() - started) * 1000)}",
        phase="render",
    )
    return page


_SEARCH_SCRIPT = """<script>
const results = document.getElementById('results');
const q = document.getElementById('q');
function esc(s){ return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function row(t){
  return '<li><a href="/?id='+encodeURIComponent(t.id)+'">' +
         '<span class="mono">todo:'+esc(t.short)+'</span> '+esc(t.summary || '(no summary)')+'</a> ' +
         '<span class="r-utime">'+esc(t.utime)+'</span> <span class="r-state">'+esc(t.state)+'</span></li>';
}
function paint(rows){ results.innerHTML = rows.length ? rows.map(row).join('') : '<li class="hint">no matches</li>'; }
paint(__DATA__);
var timer = null;
q.addEventListener('input', function(){
  clearTimeout(timer);
  timer = setTimeout(function(){
    fetch('/search?q='+encodeURIComponent(q.value)).then(function(r){ return r.json(); }).then(paint).catch(function(){});
  }, 200);
});
</script>"""


def render_search_page(root: Path, rows: List[JsonDict]) -> str:
    """Render the search landing page over *rows* (structured todo rows).

    *rows* is the initial (empty-query) result set; the search box then calls
    ``/search?q=`` for live vector-search results. Row rendering happens in one
    place -- the JS template -- from the structured fields provided by the
    caller, so the page does not re-derive summary/state/time itself.
    """
    _debug(f"render_search_page count={len(rows)}", phase="render")
    script = _SEARCH_SCRIPT.replace("__DATA__", _embed_json(rows))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>todos</title>
  {_STYLE}
</head>
<body class="search">
  <header><div class="title">Todos</div>
    <div class="meta">{html.escape(str(root))} &middot; vector search &middot; {len(rows)} todos</div>
  </header>
  <div id="top">
    <input id="q" class="search-box" type="text" placeholder="search todos (vector search)" autofocus>
    <ul id="results" class="results"></ul>
  </div>
  {script}
</body>
</html>
"""


def serve(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    initial_id: Optional[str] = None,
    resolver: Callable[[str], "tuple[Path, JsonDict]"],
    searcher: Callable[[str], List[JsonDict]],
) -> str:
    """Start the viewer and serve until interrupted.

    ``?id=<selector>`` renders that todo via *resolver*, which returns the
    ``(repo_root, todo)`` pair (the repo is where that todo's diffs come from).
    A bare path renders the search page, whose box calls ``/search?q=`` -> a
    JSON list of rows from *searcher(query)* (an empty query lists all todos).
    *initial_id* only shapes the printed URL so the browser opens straight onto
    that todo.
    """
    _debug(f"serve host={host} port={port} root={root} initial_id={initial_id}", phase="serve")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path == "/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                try:
                    rows = searcher(query)
                except TodoWebError as exc:
                    self.send_error(400, str(exc))
                    return
                self._respond(
                    json.dumps(rows).encode("utf-8"), "application/json; charset=utf-8"
                )
                return
            if parsed.path not in {"/", "/index.html"}:
                self.send_error(404)
                return
            todo_id = parse_qs(parsed.query).get("id", [None])[0]
            try:
                if todo_id:
                    todo_root, todo = resolver(todo_id)
                    payload = render_todo_page(todo_root, todo)
                else:
                    payload = render_search_page(root, searcher(""))
            except TodoWebError as exc:
                self.send_error(400, str(exc))
                return
            self._respond(payload.encode("utf-8"), "text/html; charset=utf-8")

        def _respond(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            if os.environ.get("TODO_WEB_LOG") or _debug_enabled():
                super().log_message(format, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    base = f"http://{host}:{server.server_port}/"
    url = f"{base}?id={initial_id}" if initial_id else base
    print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return url
    finally:
        server.server_close()
    return url

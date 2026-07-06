"""Web viewer for completed todo commit and ticket graphs."""

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
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse

JsonDict = Dict[str, Any]

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
    out_bytes = len(result.stdout.encode("utf-8", errors="replace"))
    err_bytes = len(result.stderr.encode("utf-8", errors="replace"))
    _debug(
        f"done {cmd} rc={result.returncode} elapsed_ms={elapsed_ms} "
        f"stdout_bytes={out_bytes} stderr_bytes={err_bytes}",
        phase="git",
    )
    if elapsed_ms >= 1000:
        _debug(f"SLOW git ({elapsed_ms}ms): {cmd}", phase="git.slow")
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _debug(f"git failed: {detail}", phase="git.error")
        raise TodoWebError(f"git {' '.join(args)} failed: {detail}")
    return result


def normalize_todo(todo: JsonDict) -> JsonDict:
    """Normalize legacy todo fields for graph walking."""
    if "Chunks" in todo and "WorkItems" not in todo:
        todo["WorkItems"] = todo.pop("Chunks")
    if "Subtickets" in todo and "Subtodos" not in todo:
        todo["Subtodos"] = todo.pop("Subtickets")
    return todo


def current_state_name(todo: JsonDict) -> Optional[str]:
    """Return the single State key, if present."""
    state = todo.get("State")
    if not isinstance(state, dict) or len(state) != 1:
        return None
    return next(iter(state.keys()))


def read_todo_at_ref(root: Path, ref: str) -> Optional[JsonDict]:
    """Read TODO.json at *ref*, returning None when absent or invalid."""
    _debug(f"read_todo_at_ref ref={ref!r}")
    result = run_git(root, "show", f"{ref}:TODO.json", check=False)
    if result.returncode != 0:
        _debug(f"read_todo_at_ref missing ref={ref!r}")
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        _debug(f"read_todo_at_ref invalid json ref={ref!r}")
        return None
    if not isinstance(parsed, dict):
        _debug(f"read_todo_at_ref not a dict ref={ref!r}")
        return None
    todo_id = str(parsed.get("Id") or "")[:8]
    _debug(f"read_todo_at_ref ok ref={ref!r} id={todo_id}")
    return normalize_todo(parsed)


def branch_exists(root: Path, name: str) -> bool:
    """Return True when a local branch exists."""
    _debug(f"branch_exists name={name!r}")
    result = run_git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False)
    exists = result.returncode == 0
    _debug(f"branch_exists name={name!r} exists={exists}")
    return exists


def default_base_branch(root: Path, ticket: JsonDict) -> Optional[str]:
    """Choose the base branch for a ticket's commit walk."""
    ticket_id = str(ticket.get("Id") or "")[:8]
    _debug(f"default_base_branch ticket={ticket_id}")
    parent = ticket.get("Parent")
    if isinstance(parent, dict) and parent.get("Branch"):
        branch = str(parent["Branch"])
        if branch_exists(root, branch):
            _debug(f"default_base_branch ticket={ticket_id} chose parent={branch!r}")
            return branch
    for candidate in ("dev", "main", "master"):
        if branch_exists(root, candidate):
            _debug(f"default_base_branch ticket={ticket_id} chose fallback={candidate!r}")
            return candidate
    _debug(f"default_base_branch ticket={ticket_id} found none")
    return None


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


def branch_commits(root: Path, ticket: JsonDict) -> List[JsonDict]:
    """Return chronological commits that belong to a ticket branch."""
    branch = str(ticket.get("Branch") or "")
    ticket_id = str(ticket.get("Id") or "")[:8]
    _debug(f"branch_commits ticket={ticket_id} branch={branch!r}")
    if not branch or not branch_exists(root, branch):
        _debug(f"branch_commits ticket={ticket_id} skip: missing branch")
        return []
    base = default_base_branch(root, ticket)
    if not base:
        _debug(f"branch_commits ticket={ticket_id} skip: no base branch")
        return []
    range_spec = f"{base}..{branch}"
    _debug(f"branch_commits ticket={ticket_id} log range={range_spec!r}")
    result = run_git(
        root,
        "log",
        "--reverse",
        "--format=%H%x00%h%x00%s",
        range_spec,
        check=False,
    )
    if result.returncode != 0:
        _debug(f"branch_commits ticket={ticket_id} git log failed rc={result.returncode}")
        return []
    commits: List[JsonDict] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x00", 2)
        if len(parts) != 3:
            continue
        commits.append({"hash": parts[0], "short": parts[1], "subject": parts[2]})
    _debug(f"branch_commits ticket={ticket_id} count={len(commits)}")
    return commits


def load_child_ticket(root: Path, entry: JsonDict) -> JsonDict:
    """Load a child ticket from its branch, or fall back to the Subtodos snapshot."""
    entry_id = str(entry.get("Id") or "")
    child_id = entry_id[:8]
    branch = str(entry.get("Branch") or "")
    _debug(f"load_child_ticket id={child_id} branch={branch!r}")
    if branch:
        child = read_todo_at_ref(root, branch)
        if child is not None:
            loaded_id = str(child.get("Id") or "")
            if loaded_id == entry_id:
                subtodos = len(list(child.get("Subtodos") or []))
                _debug(
                    f"load_child_ticket id={child_id} loaded from branch subtodos={subtodos}"
                )
                return child
            _debug(
                f"load_child_ticket id={child_id} branch file has id={loaded_id[:8]} "
                f"using snapshot fallback",
            )
    _debug(f"load_child_ticket id={child_id} using snapshot fallback")
    return {
        "Id": entry_id,
        "Branch": branch,
        "Summary": {"raw": entry.get("Summary", "")},
        "State": {str(entry.get("State", "init")): {}},
        "Subtodos": [],
    }


def lane_node(root: Path, ticket: JsonDict, *, depth: int, has_children: bool) -> JsonDict:
    """Build one timeline lane from a todo: its metadata plus branch commits."""
    summary = ticket.get("Summary")
    return {
        "id": str(ticket.get("Id") or ""),
        "branch": str(ticket.get("Branch") or ""),
        "summary": summary.get("raw", "") if isinstance(summary, dict) else "",
        "state": current_state_name(ticket) or "?",
        "depth": depth,
        "repo": str(root),
        "has_children": has_children,
        "commits": branch_commits(root, ticket),
    }


def build_lanes(root: Path, ticket: JsonDict) -> List[JsonDict]:
    """Build one level of side-by-side lanes: the root todo then each direct subtodo.

    Deeper nesting is not expanded inline; a subtodo that has its own subtodos is
    flagged so the viewer can offer a re-root link to open it as a new top level.
    """
    ticket_id = str(ticket.get("Id") or "")
    _debug(f"build_lanes root id={ticket_id[:8]}", phase="lanes")
    lanes = [lane_node(root, ticket, depth=0, has_children=False)]
    for entry in list(ticket.get("Subtodos") or []):
        if not isinstance(entry, dict):
            continue
        child = load_child_ticket(root, entry)
        has_children = bool(list(child.get("Subtodos") or []))
        lanes.append(lane_node(root, child, depth=1, has_children=has_children))
    _debug(f"build_lanes root id={ticket_id[:8]} lanes={len(lanes)}", phase="lanes")
    return lanes


def commit_message(root: Path, commit_hash: str) -> str:
    """Return the full commit message (subject + body) for one commit."""
    _debug(f"commit_message commit={commit_hash}")
    result = run_git(root, "show", "-s", "--format=%B", commit_hash, check=False)
    if result.returncode != 0:
        return "[commit message unavailable]\n"
    return result.stdout


def diff_unified(root: Path, commit_hash: str) -> str:
    """Return a unified patch for one commit."""
    _debug(f"diff_unified commit={commit_hash}")
    started = time.monotonic()
    result = run_git(root, "show", "--format=", "--patch", "--find-renames", commit_hash)
    patch_bytes = len(result.stdout.encode("utf-8", errors="replace"))
    _debug(
        f"diff_unified commit={commit_hash} patch_bytes={patch_bytes} "
        f"elapsed_ms={int((time.monotonic() - started) * 1000)}",
        phase="diff",
    )
    return result.stdout


def changed_files(root: Path, commit_hash: str) -> List[str]:
    """Return files changed by one commit."""
    _debug(f"changed_files commit={commit_hash}")
    result = run_git(
        root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit_hash,
        check=False,
    )
    if result.returncode != 0:
        _debug(f"changed_files commit={commit_hash} failed rc={result.returncode}")
        return []
    paths = [line for line in result.stdout.splitlines() if line.strip()]
    _debug(f"changed_files commit={commit_hash} count={len(paths)}")
    return paths


def blob_at(root: Path, commitish: str, path: str) -> str:
    """Return file contents at commitish:path, or a placeholder for missing blobs."""
    _debug(f"blob_at commitish={commitish!r} path={path!r}")
    result = run_git(root, "show", f"{commitish}:{path}", check=False)
    if result.returncode != 0:
        _debug(f"blob_at missing commitish={commitish!r} path={path!r}")
        return "[file absent]\n"
    return result.stdout


def diff_prepost(root: Path, commit_hash: str) -> str:
    """Render pre/post file contents for one commit."""
    _debug(f"diff_prepost commit={commit_hash}")
    started = time.monotonic()
    parts: List[str] = []
    for path in changed_files(root, commit_hash):
        before = blob_at(root, f"{commit_hash}^", path)
        after = blob_at(root, commit_hash, path)
        parts.append(
            '<section class="file-pair">'
            f"<h3>{html.escape(path)}</h3>"
            '<div class="split">'
            f'<pre><code>{html.escape(before)}</code></pre>'
            f'<pre><code>{html.escape(after)}</code></pre>'
            "</div>"
            "</section>"
        )
    html_out = "\n".join(parts) if parts else "<p>No file-level diff available.</p>"
    _debug(
        f"diff_prepost commit={commit_hash} sections={len(parts)} "
        f"elapsed_ms={int((time.monotonic() - started) * 1000)}",
        phase="diff",
    )
    return html_out


def work_item_shas(ticket: JsonDict) -> List[str]:
    """Return every commit sha recorded on the ticket's WorkItems, in order."""
    shas: List[str] = []
    items = ticket.get("WorkItems") or []
    if not isinstance(items, list):
        return shas
    for item in items:
        if not isinstance(item, dict):
            continue
        sha = item.get("sha")
        if isinstance(sha, str) and sha:
            shas.append(sha)
        # tolerate the legacy commits-list shape
        for legacy in item.get("commits") or []:
            if isinstance(legacy, str) and legacy:
                shas.append(legacy)
    return shas


def render_page(
    root: Path,
    ticket: JsonDict,
    *,
    selected_commit: Optional[str] = None,
    mode: str = "unified",
) -> str:
    """Render the timeline (top) plus info/diff (bottom) HTML viewer."""
    ticket_id = str(ticket.get("Id") or "")
    started = time.monotonic()
    _debug(
        f"render_page enter root={root} ticket={ticket_id[:8]} "
        f"selected_commit={selected_commit!r} mode={mode!r}",
        phase="render",
    )
    if mode not in {"unified", "prepost"}:
        raise TodoWebError("mode must be unified or prepost")
    lanes = build_lanes(root, ticket)
    allowed = {commit["hash"] for lane in lanes for commit in lane["commits"]}
    allowed |= set(work_item_shas(ticket))
    commit = selected_commit or None
    if commit and commit not in allowed:
        raise TodoWebError(f"commit {commit!r} is not part of this todo")
    github = github_repo_url(repo_origin(root))
    root_sel = ticket_id or "self"
    if commit:
        info_html = _commit_info(root, commit, mode, root_sel, github)
    else:
        info_html = _root_info(root, ticket, root_sel, mode)
    page = _html_shell(root, ticket, lanes, commit, root_sel, mode, info_html)
    _debug(
        f"render_page exit ticket={ticket_id[:8]} html_bytes={len(page.encode('utf-8'))} "
        f"elapsed_ms={int((time.monotonic() - started) * 1000)}",
        phase="render",
    )
    return page


def _reroot_href(target_id: str) -> str:
    """Link that re-displays *target_id* as the top-level timeline root."""
    return html.escape(f"/?root={target_id}#top")


def _commit_href(root_sel: str, commit_hash: str, mode: str) -> str:
    """Link that keeps the current root but selects *commit_hash* in the info pane."""
    return html.escape(f"/?root={root_sel}&commit={commit_hash}&mode={mode}#info")


def _lane_html(
    root: Path,
    lane: JsonDict,
    root_sel: str,
    mode: str,
    selected_commit: Optional[str],
) -> str:
    """Render one side-by-side lane: header plus its commits stacked oldest-first."""
    is_root = int(lane["depth"]) == 0
    lane_id = str(lane["id"])
    expand = ""
    if lane["has_children"]:
        expand = (
            f'<a class="expand" title="open this subtodo as its own timeline" '
            f'href="{_reroot_href(lane_id)}">(+)</a>'
        )
    id_link = (
        f'<a href="{_reroot_href(lane_id)}">{html.escape(lane_id[:8] or "?")}</a>'
        if lane_id
        else "?"
    )
    parts: List[str] = [
        f'<div class="lane{" root" if is_root else ""}">',
        '<div class="lane-head">',
        expand,
        f'<div class="lane-title">{html.escape(lane["summary"] or "(no summary)")}</div>',
        f'<div class="meta">todo {id_link} &middot; {html.escape(lane["branch"] or "-")} '
        f'&middot; {html.escape(lane["state"])}</div>',
        "</div>",
        '<ol class="commits">',
    ]
    for commit in lane["commits"]:
        selected = " selected" if commit["hash"] == selected_commit else ""
        href = _commit_href(root_sel, commit["hash"], mode)
        parts.append(
            f'<li class="commit{selected}"><a href="{href}">'
            f'{html.escape(commit["short"])} {html.escape(commit["subject"])}</a></li>'
        )
    if not lane["commits"]:
        parts.append('<li class="commit empty">no commits</li>')
    parts.append("</ol></div>")
    return "".join(parts)


def _root_info(root: Path, ticket: JsonDict, root_sel: str, mode: str) -> str:
    """Default bottom-pane content: root metadata and the WorkItems plan."""
    items = ticket.get("WorkItems") or []
    rows: List[str] = []
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            done = bool(item.get("done"))
            mark = "[x]" if done else "[ ]"
            kind = html.escape(str(item.get("kind", "")))
            kind_html = f' <span class="kind">{kind}</span>' if kind else ""
            summary = html.escape(str(item.get("summary", "")))
            item_shas = [item["sha"]] if isinstance(item.get("sha"), str) and item.get("sha") else []
            item_shas += [s for s in (item.get("commits") or []) if isinstance(s, str) and s]
            sha_links = " ".join(
                f'<a href="{_commit_href(root_sel, sha, mode)}">{html.escape(sha[:8])}</a>'
                for sha in item_shas
            )
            sha_html = f' <span class="shas">{sha_links}</span>' if sha_links else ""
            rows.append(f'<li>{mark}{kind_html} {summary}{sha_html}</li>')
    plan = f'<ol class="workitems">{"".join(rows)}</ol>' if rows else "<p>No work items.</p>"
    return (
        '<div class="info-body">'
        "<h2>More info</h2>"
        '<div class="meta">Click any commit above to see its message and diff here. '
        "Click a todo Id or (+) to open that todo as its own timeline.</div>"
        f"<h3>Work plan</h3>{plan}"
        "</div>"
    )


def _commit_info(
    root: Path,
    commit: str,
    mode: str,
    root_sel: str,
    github: Optional[str],
) -> str:
    """Bottom-pane content for a selected commit: message (left), diff (right)."""
    message = html.escape(commit_message(root, commit))
    if mode == "unified":
        diff_inner = f"<pre><code>{html.escape(diff_unified(root, commit))}</code></pre>"
    else:
        diff_inner = diff_prepost(root, commit)
    mode_toggle = (
        f'<a href="{_commit_href(root_sel, commit, "unified")}">unified</a> &middot; '
        f'<a href="{_commit_href(root_sel, commit, "prepost")}">pre/post</a>'
    )
    github_link = ""
    if github:
        gh_href = html.escape(f"{github}/commit/{commit}")
        github_link = f' &middot; <a href="{gh_href}">GitHub</a>'
    return (
        '<div class="info-split">'
        '<div class="commit-msg">'
        f"<h3>{html.escape(commit[:8])}</h3>"
        f"<pre><code>{message}</code></pre>"
        "</div>"
        '<div class="commit-diff diff-code">'
        f'<div class="diff-bar">{mode_toggle}{github_link}</div>'
        f"{diff_inner}"
        "</div>"
        "</div>"
    )


def _html_shell(
    root: Path,
    ticket: JsonDict,
    lanes: Sequence[JsonDict],
    selected_commit: Optional[str],
    root_sel: str,
    mode: str,
    info_html: str,
) -> str:
    """Assemble the timeline (top) and info (bottom) panes."""
    title = html.escape(ticket.get("Summary", {}).get("raw", "todo timeline"))
    ticket_id = str(ticket.get("Id") or "")
    lane_html = "".join(
        _lane_html(root, lane, root_sel, mode, selected_commit) for lane in lanes
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ margin: 0; font: 14px/1.4 -apple-system, BlinkMacSystemFont, sans-serif; color: #17202a; }}
    header {{ padding: 10px 16px; border-bottom: 1px solid #d8dee4; background: #f6f8fa; }}
    a {{ color: #0969da; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .meta {{ color: #57606a; font-size: 12px; overflow-wrap: anywhere; }}
    #top {{ height: 45vh; overflow: auto; border-bottom: 3px solid #d8dee4; }}
    #info {{ height: 47vh; overflow: auto; padding: 12px 16px; }}
    .axis {{ padding: 6px 16px 0; color: #57606a; font-size: 12px; }}
    .lanes {{ display: flex; gap: 10px; align-items: flex-start; padding: 8px 16px 16px; }}
    .lane {{ flex: 0 0 240px; width: 240px; border: 1px solid #d8dee4; border-radius: 6px;
             background: #fff; }}
    .lane.root {{ border-color: #8c959f; background: #f6f8fa; }}
    .lane-head {{ position: relative; padding: 8px; border-bottom: 1px solid #eaeef2; }}
    .lane-title {{ font-weight: 700; font-size: 13px; overflow-wrap: anywhere; }}
    .expand {{ position: absolute; top: 6px; right: 8px; font-weight: 700; }}
    .commits {{ list-style: none; margin: 0; padding: 6px; }}
    .commit {{ padding: 4px 6px; border-radius: 5px; font-size: 12px; overflow-wrap: anywhere; }}
    .commit.selected {{ background: #ddf4ff; }}
    .commit.empty {{ color: #8c959f; }}
    .workitems {{ margin: 6px 0 0; padding-left: 20px; }}
    .workitems .shas a {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .info-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: 100%; }}
    .commit-msg pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; }}
    .diff-code {{ background: #0d1117; color: #e6edf3; border-radius: 6px; padding: 12px; }}
    .diff-code a {{ color: #79c0ff; }}
    .diff-bar {{ margin-bottom: 8px; }}
    pre {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .file-pair {{ margin-bottom: 16px; }}
    .file-pair h3 {{ color: #e6edf3; }}
  </style>
</head>
<body>
  <header id="top">
    <strong><a href="{_reroot_href(ticket_id or "self")}">{title}</a></strong>
    <div class="meta">root {html.escape(ticket_id)} &middot; repo {html.escape(str(root))}</div>
  </header>
  <section id="top-pane">
    <div class="axis">time flows down &darr; &middot; lanes are parallel subtodos</div>
    <div id="lanes-scroll" style="max-height: 40vh; overflow: auto;">
      <div class="lanes">{lane_html}</div>
    </div>
  </section>
  <section id="info">
    {info_html}
  </section>
</body>
</html>
"""


def serve(
    root: Path,
    ticket: JsonDict,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    resolver: Optional[Callable[[str], JsonDict]] = None,
) -> str:
    """Start the todo web viewer and serve until interrupted.

    *resolver* maps a todo selector (from the ?root= query param) to a ticket so
    that todo-Id links can re-root the timeline on another todo. When omitted,
    every request renders the ticket passed here.
    """
    ticket_id = str(ticket.get("Id") or "")[:8]
    subtodos = len(list(ticket.get("Subtodos") or []))
    _debug(
        f"serve starting host={host} port={port} root={root} ticket={ticket_id} "
        f"subtodos={subtodos} debug={_debug_enabled()} log={bool(os.environ.get('TODO_WEB_LOG'))}",
        phase="serve",
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            started = time.monotonic()
            parsed = urlparse(self.path)
            _debug(
                f"GET path={self.path!r} client={self.client_address[0]}:{self.client_address[1]}",
                phase="http",
            )
            if parsed.path not in {"/", "/index.html"}:
                _debug(f"GET 404 path={parsed.path!r}", phase="http")
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            commit = params.get("commit", [None])[0]
            mode = params.get("mode", ["unified"])[0]
            root_sel = params.get("root", [None])[0]
            try:
                target = ticket
                if root_sel and resolver is not None:
                    target = resolver(root_sel)
                payload = render_page(root, target, selected_commit=commit, mode=mode)
            except TodoWebError as exc:
                _debug(f"GET 400 error={exc}", phase="http")
                self.send_error(400, str(exc))
                return
            encoded = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            _debug(
                f"GET 200 bytes={len(encoded)} elapsed_ms={int((time.monotonic() - started) * 1000)} "
                f"commit={commit!r} mode={mode!r}",
                phase="http",
            )

        def log_message(self, format: str, *args: object) -> None:
            if os.environ.get("TODO_WEB_LOG") or _debug_enabled():
                super().log_message(format, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}/"
    print(url, flush=True)
    if _debug_enabled():
        print(
            "todo_web: TODO_WEB_DEBUG=1 (stderr traces on). "
            "Set TODO_WEB_LOG=1 for access-log style lines.",
            file=sys.stderr,
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return url
    finally:
        server.server_close()
    return url

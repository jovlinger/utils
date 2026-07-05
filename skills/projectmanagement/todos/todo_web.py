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
from typing import Any, Dict, List, Optional, Sequence
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


def walk_todos(
    root: Path,
    ticket: JsonDict,
    depth: int = 0,
    visited: Optional[set[str]] = None,
) -> List[JsonDict]:
    """Walk a todo and its child tickets, including each branch's commits."""
    if visited is None:
        visited = set()
    ticket_id = str(ticket.get("Id") or "")
    ticket_short = ticket_id[:8]
    if ticket_id and ticket_id in visited:
        _debug(
            f"walk_todos skip already visited id={ticket_short} depth={depth}",
            phase="walk",
        )
        return []
    if ticket_id:
        visited.add(ticket_id)
    branch = str(ticket.get("Branch") or "")
    subtodo_count = len(list(ticket.get("Subtodos") or []))
    _debug(
        f"walk_todos enter id={ticket_id} branch={branch!r} depth={depth} "
        f"subtodos={subtodo_count}",
        phase="walk",
    )
    started = time.monotonic()
    summary = ticket.get("Summary")
    node = {
        "id": str(ticket.get("Id") or ""),
        "branch": str(ticket.get("Branch") or ""),
        "summary": summary.get("raw", "") if isinstance(summary, dict) else "",
        "state": current_state_name(ticket) or "?",
        "depth": depth,
        "repo": str(root),
        "commits": branch_commits(root, ticket),
    }
    nodes = [node]
    child_index = 0
    for entry in list(ticket.get("Subtodos") or []):
        if isinstance(entry, dict):
            child_index += 1
            child_id = str(entry.get("Id") or "")[:8]
            _debug(
                f"walk_todos child {child_index}/{subtodo_count} parent={ticket_id} "
                f"child={child_id} depth={depth + 1}",
                phase="walk",
            )
            nodes.extend(
                walk_todos(root, load_child_ticket(root, entry), depth + 1, visited)
            )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    _debug(
        f"walk_todos exit id={ticket_id} depth={depth} nodes={len(nodes)} "
        f"commits={sum(len(n['commits']) for n in nodes)} elapsed_ms={elapsed_ms}",
        phase="walk",
    )
    return nodes


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


def flatten_commits(nodes: Sequence[JsonDict]) -> List[JsonDict]:
    """Flatten node commits with ticket metadata attached."""
    flattened: List[JsonDict] = []
    for node in nodes:
        for commit in node["commits"]:
            enriched = dict(commit)
            enriched["ticket_id"] = node["id"]
            enriched["ticket_summary"] = node["summary"]
            enriched["branch"] = node["branch"]
            enriched["repo"] = node["repo"]
            flattened.append(enriched)
    return flattened


def render_page(
    root: Path,
    ticket: JsonDict,
    *,
    selected_commit: Optional[str] = None,
    mode: str = "unified",
) -> str:
    """Render the complete two-pane HTML viewer."""
    ticket_id = str(ticket.get("Id") or "")[:8]
    started = time.monotonic()
    _debug(
        f"render_page enter root={root} ticket={ticket_id} "
        f"selected_commit={selected_commit!r} mode={mode!r}",
        phase="render",
    )
    nodes = walk_todos(root, ticket)
    commits = flatten_commits(nodes)
    _debug(
        f"render_page walked nodes={len(nodes)} commits={len(commits)} ticket={ticket_id}",
        phase="render",
    )
    commit = selected_commit or (commits[0]["hash"] if commits else "")
    if commit and commit not in {item["hash"] for item in commits}:
        raise TodoWebError(f"commit {commit!r} is not part of this todo graph")
    if mode not in {"unified", "prepost"}:
        raise TodoWebError("mode must be unified or prepost")
    origin = repo_origin(root)
    github = github_repo_url(origin)
    _debug(
        f"render_page diff commit={commit!r} mode={mode!r} github={bool(github)}",
        phase="render",
    )
    diff_html = (
        f"<pre><code>{html.escape(diff_unified(root, commit))}</code></pre>"
        if commit and mode == "unified"
        else diff_prepost(root, commit)
        if commit
        else "<p>No commits found for this todo graph.</p>"
    )
    page = _html_shell(root, ticket, nodes, commits, commit, mode, github, diff_html)
    _debug(
        f"render_page exit ticket={ticket_id} html_bytes={len(page.encode('utf-8'))} "
        f"elapsed_ms={int((time.monotonic() - started) * 1000)}",
        phase="render",
    )
    return page


def _html_shell(
    root: Path,
    ticket: JsonDict,
    nodes: Sequence[JsonDict],
    commits: Sequence[JsonDict],
    selected_commit: str,
    mode: str,
    github: Optional[str],
    diff_html: str,
) -> str:
    """Assemble graph and diff panes."""
    title = html.escape(ticket.get("Summary", {}).get("raw", "todo postmortem"))
    graph_parts: List[str] = []
    for node in nodes:
        indent = int(node["depth"]) * 24
        graph_parts.append(
            f'<article class="ticket" style="margin-left:{indent}px">'
            f'<div class="ticket-title">{html.escape(node["summary"])}</div>'
            f'<div class="meta">todo {html.escape(node["id"])} · branch '
            f'{html.escape(node["branch"])} · state {html.escape(node["state"])} · repo '
            f'{html.escape(node["repo"])}</div>'
            '<ol class="commits">'
        )
        for commit in node["commits"]:
            selected = " selected" if commit["hash"] == selected_commit else ""
            url = f"/?commit={commit['hash']}&mode={mode}#diff"
            github_link = ""
            if github:
                gh_href = f"{github}/commit/{commit['hash']}"
                github_link = f' <a class="github" href="{html.escape(gh_href)}">GitHub</a>'
            graph_parts.append(
                f'<li class="commit{selected}"><a href="{html.escape(url)}">'
                f'{html.escape(commit["short"])} {html.escape(commit["subject"])}</a>'
                f'<div class="meta">hash {html.escape(commit["hash"])} · repo '
                f'{html.escape(str(root))}{github_link}</div></li>'
            )
        graph_parts.append("</ol></article>")
    mode_toggle = (
        f'<a href="/?commit={html.escape(selected_commit)}&mode=unified#diff">unified</a>'
        " · "
        f'<a href="/?commit={html.escape(selected_commit)}&mode=prepost#diff">pre/post</a>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ margin: 0; font: 14px/1.4 -apple-system, BlinkMacSystemFont, sans-serif; color: #17202a; }}
    header {{ padding: 12px 16px; border-bottom: 1px solid #d8dee4; background: #f6f8fa; }}
    .pane {{ padding: 16px; }}
    #graph {{ height: 42vh; overflow: auto; border-bottom: 3px solid #d8dee4; }}
    #diff {{ height: 50vh; overflow: auto; background: #0d1117; color: #e6edf3; }}
    .ticket {{ margin: 0 0 14px; padding-left: 12px; border-left: 3px solid #8c959f; }}
    .ticket-title {{ font-weight: 700; }}
    .meta {{ color: #57606a; font-size: 12px; overflow-wrap: anywhere; }}
    .commits {{ margin: 8px 0 0 20px; padding: 0; }}
    .commit {{ padding: 4px 6px; border-radius: 5px; }}
    .commit.selected {{ background: #ddf4ff; }}
    a {{ color: #0969da; text-decoration: none; }}
    #diff a {{ color: #79c0ff; }}
    pre {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .file-pair {{ margin-bottom: 16px; }}
    .file-pair h3 {{ color: #e6edf3; }}
  </style>
</head>
<body>
  <header>
    <strong>{title}</strong>
    <div class="meta">root {html.escape(str(ticket.get("Id", "")))} · repo {html.escape(str(root))}</div>
  </header>
  <section id="graph" class="pane">
    {"".join(graph_parts)}
  </section>
  <section id="diff" class="pane">
    <div>{mode_toggle}</div>
    <h2>Diff {html.escape(selected_commit)}</h2>
    {diff_html}
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
) -> str:
    """Start the todo web viewer and serve until interrupted."""
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
            try:
                payload = render_page(root, ticket, selected_commit=commit, mode=mode)
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

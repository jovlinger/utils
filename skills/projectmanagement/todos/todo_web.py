"""Web viewer for completed todo commit and ticket graphs."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse

JsonDict = Dict[str, Any]


class TodoWebError(Exception):
    """User-facing web viewer error."""


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in *root* and return the completed process."""
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
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


def branch_exists(root: Path, name: str) -> bool:
    """Return True when a local branch exists."""
    result = run_git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False)
    return result.returncode == 0


def default_base_branch(root: Path, ticket: JsonDict) -> Optional[str]:
    """Choose the base branch for a ticket's commit walk."""
    parent = ticket.get("Parent")
    if isinstance(parent, dict) and parent.get("Branch"):
        branch = str(parent["Branch"])
        if branch_exists(root, branch):
            return branch
    for candidate in ("dev", "main", "master"):
        if branch_exists(root, candidate):
            return candidate
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
    if not branch or not branch_exists(root, branch):
        return []
    base = default_base_branch(root, ticket)
    if not base:
        return []
    result = run_git(
        root,
        "log",
        "--reverse",
        "--format=%H%x00%h%x00%s",
        f"{base}..{branch}",
        check=False,
    )
    if result.returncode != 0:
        return []
    commits: List[JsonDict] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x00", 2)
        if len(parts) != 3:
            continue
        commits.append({"hash": parts[0], "short": parts[1], "subject": parts[2]})
    return commits


def load_child_ticket(root: Path, entry: JsonDict) -> JsonDict:
    """Load a child ticket from its branch, or fall back to the Subtodos snapshot."""
    branch = str(entry.get("Branch") or "")
    if branch:
        child = read_todo_at_ref(root, branch)
        if child is not None:
            return child
    return {
        "Id": entry.get("Id", ""),
        "Branch": branch,
        "Summary": {"raw": entry.get("Summary", "")},
        "State": {str(entry.get("State", "init")): {}},
        "Subtodos": [],
    }


def walk_todos(root: Path, ticket: JsonDict, depth: int = 0) -> List[JsonDict]:
    """Walk a todo and its child tickets, including each branch's commits."""
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
    for entry in list(ticket.get("Subtodos") or []):
        if isinstance(entry, dict):
            nodes.extend(walk_todos(root, load_child_ticket(root, entry), depth + 1))
    return nodes


def diff_unified(root: Path, commit_hash: str) -> str:
    """Return a unified patch for one commit."""
    result = run_git(root, "show", "--format=", "--patch", "--find-renames", commit_hash)
    return result.stdout


def changed_files(root: Path, commit_hash: str) -> List[str]:
    """Return files changed by one commit."""
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
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def blob_at(root: Path, commitish: str, path: str) -> str:
    """Return file contents at commitish:path, or a placeholder for missing blobs."""
    result = run_git(root, "show", f"{commitish}:{path}", check=False)
    if result.returncode != 0:
        return "[file absent]\n"
    return result.stdout


def diff_prepost(root: Path, commit_hash: str) -> str:
    """Render pre/post file contents for one commit."""
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
    return "\n".join(parts) if parts else "<p>No file-level diff available.</p>"


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
    nodes = walk_todos(root, ticket)
    commits = flatten_commits(nodes)
    commit = selected_commit or (commits[0]["hash"] if commits else "")
    if commit and commit not in {item["hash"] for item in commits}:
        raise TodoWebError(f"commit {commit!r} is not part of this todo graph")
    if mode not in {"unified", "prepost"}:
        raise TodoWebError("mode must be unified or prepost")
    origin = repo_origin(root)
    github = github_repo_url(origin)
    diff_html = (
        f"<pre><code>{html.escape(diff_unified(root, commit))}</code></pre>"
        if commit and mode == "unified"
        else diff_prepost(root, commit)
        if commit
        else "<p>No commits found for this todo graph.</p>"
    )
    return _html_shell(root, ticket, nodes, commits, commit, mode, github, diff_html)


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

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/index.html"}:
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            commit = params.get("commit", [None])[0]
            mode = params.get("mode", ["unified"])[0]
            try:
                payload = render_page(root, ticket, selected_commit=commit, mode=mode)
            except TodoWebError as exc:
                self.send_error(400, str(exc))
                return
            encoded = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            if os.environ.get("TODO_WEB_LOG"):
                super().log_message(format, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}/"
    print(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return url
    finally:
        server.server_close()
    return url

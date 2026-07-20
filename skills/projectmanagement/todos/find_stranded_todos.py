#!/usr/bin/env python3
"""find_stranded_todos.py -- recover todos hidden on un-merged todo branches.

In the deployment where `.todo/storage` (the todo store) is VERSIONED, the store
is captured by git and therefore differs per branch. An un-merged todo branch
can carry todos in its committed store that never made it back to the main
checkout -- they are "hidden" there: invisible to `todo.py ls` at gitroot even
though they exist on the branch.

This helper finds them by set-diffing `todo.py ls`:

  * baseline = `todo.py ls` at gitroot (the current checkout's store).
  * per branch = `todo.py ls` against the branch checkout's own `.todo` store
    (TODO_DIR=<checkout>/.todo, because a linked worktree otherwise resolves the
    store back to the MAIN checkout, not the branch).

Todos whose short Id appears in a branch's `ls` but not in the baseline are the
branch-hidden ones. `todo.py ls` for a branch is a super-set of that branch's
`self` todo (a versioned store may hold many todos), so the diff subsumes the
old self-only check.

  --dry-run  : only list the branch-hidden todos; change nothing.
  (default)  : move each hidden todo into the main (gitroot) store, by reading
               it from the branch store and importing it with `todo.py
               import-json` (the ticket carries its own Branch).

updated_dt is deliberately NOT consulted: a todo already in the baseline store
is left untouched regardless of which copy is newer; only short Ids that are
strictly extra on a branch are moved in.

All todo access goes through todo.py; this script never parses TODO.json or the
store itself. Run it from inside the target repo (the repo is taken from the
current directory's gitroot -- there is no --repo flag). Safe to re-run.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TODO_PY = Path(__file__).resolve().with_name("todo.py")

# Todo branch convention: Branch = (Id[0:8] + "-" + kebab(summary))[:32], so the
# name always starts with the 8-hex short Id, optionally followed by "-<slug>".
BRANCH_RE = re.compile(r"^[0-9a-f]{8}(-|$)")


def _run(cmd, cwd=None, check=True):
    """Run *cmd* capturing text output; raise on non-zero when *check*."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _todo(args, cwd, todo_dir=None, check=True):
    """Invoke the sibling todo.py CLI in *cwd*, optionally with TODO_DIR set.

    Passing *todo_dir* points todo.py at a specific store (used to read a branch
    checkout's own versioned `.todo`, which a linked worktree would otherwise
    resolve back to the main checkout).
    """
    env = None
    if todo_dir is not None:
        env = dict(os.environ, TODO_DIR=str(todo_dir))
    return subprocess.run(
        [str(TODO_PY), *args], cwd=cwd, capture_output=True, text=True, check=check, env=env
    )


def gitroot():
    """Return the current directory's git worktree root, or exit if not a repo."""
    res = _run(["git", "rev-parse", "--show-toplevel"], check=False)
    if res.returncode != 0:
        sys.exit("find_stranded_todos: not in a git repository (cd into the target repo first)")
    return Path(res.stdout.strip())


def todo_named_branches(root):
    """Local branch names matching the todo branch-name convention."""
    out = _run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=root,
    ).stdout
    return [name for name in (line.strip() for line in out.splitlines()) if BRANCH_RE.match(name)]


def ls_shortmap(cwd, todo_dir=None):
    """Map short Id (Id[:8]) -> full `todo.py ls` line for the resolved store.

    Returns None when `todo.py ls` fails (e.g. the store cannot be read there).
    """
    res = _todo(["ls"], cwd=cwd, todo_dir=todo_dir, check=False)
    if res.returncode != 0:
        return None
    mapping = {}
    for line in res.stdout.splitlines():
        parts = line.split(None, 1)
        if parts:
            mapping[parts[0]] = line.rstrip()
    return mapping


def attached_worktrees(root):
    """Map branch-name -> worktree path for branches git already has checked out."""
    out = _run(["git", "worktree", "list", "--porcelain"], cwd=root).stdout
    mapping = {}
    current = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):]
        elif line.startswith("branch ") and current:
            ref = line[len("branch "):]
            mapping[ref.split("refs/heads/", 1)[-1]] = current
    return mapping


def acquire_worktree(root, branch, attached):
    """Return (path, tmpdir): a checkout of *branch*. tmpdir is None when reused.

    Reuses an already-attached worktree for the branch; otherwise adds a
    throwaway one under a fresh temp dir. Returns (None, None) if neither works.
    """
    existing = attached.get(branch)
    if existing and os.path.isdir(existing):
        return existing, None
    tmp = tempfile.mkdtemp(prefix="todo-hidden-")
    path = os.path.join(tmp, "wt")
    res = _run(["git", "worktree", "add", "--quiet", path, branch], cwd=root, check=False)
    if res.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None
    return path, tmp


def release_worktree(root, path, tmp):
    """Tear down a throwaway worktree; no-op for a reused (tmp is None) one."""
    if tmp is None:
        return
    _run(["git", "worktree", "remove", "--force", path], cwd=root, check=False)
    shutil.rmtree(tmp, ignore_errors=True)
    _run(["git", "worktree", "prune"], cwd=root, check=False)


def import_from_branch(root, worktree, short):
    """Read todo *short* from the branch store and import it into the main store.

    Returns True on success. The ticket is read from the branch checkout's own
    `.todo` and imported with its own Branch into gitroot's (main) store.
    """
    branch_todo_dir = os.path.join(worktree, ".todo")
    read = _todo(["read", short], cwd=worktree, todo_dir=branch_todo_dir, check=False)
    if read.returncode != 0:
        return False
    fd, dump = tempfile.mkstemp(prefix="todo-hidden-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(read.stdout)
        res = _todo(["import-json", "--from-json", dump], cwd=root, check=False)
        return res.returncode == 0
    finally:
        os.unlink(dump)


def main(argv=None):
    """Diff each todo branch's `todo.py ls` against gitroot's; list or import extras."""
    parser = argparse.ArgumentParser(
        description="Find todos hidden on un-merged todo branches (versioned .todo store) "
        "and move them into the main (gitroot) store.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only list the branch-hidden todos; import nothing",
    )
    args = parser.parse_args(argv)

    root = gitroot()
    baseline = ls_shortmap(root)
    if baseline is None:
        sys.exit("find_stranded_todos: `todo.py ls` failed at gitroot")
    branches = todo_named_branches(root)
    attached = attached_worktrees(root)

    print(f"repo:    {root}")
    print(f"mode:    {'dry-run (list only)' if args.dry_run else 'import'}")
    print(f"todo-named local branches: {len(branches)}; baseline todos: {len(baseline)}")

    found = {}          # short -> (branch, line): unique branch-hidden todos
    imported = []       # (short, branch) actually moved into the main store

    for branch in branches:
        worktree, tmp = acquire_worktree(root, branch, attached)
        if worktree is None:
            print(f"  ??  {branch}: could not check out (skipped)")
            continue
        try:
            branch_map = ls_shortmap(worktree, todo_dir=os.path.join(worktree, ".todo"))
            if branch_map is None:
                print(f"  ??  {branch}: `todo.py ls` failed in checkout (skipped)")
                continue
            extras = [s for s in branch_map if s not in baseline and s not in found]
            for short in sorted(extras):
                line = branch_map[short]
                found[short] = (branch, line)
                if args.dry_run:
                    print(f"  --  {line}   [branch {branch}]")
                    continue
                if import_from_branch(root, worktree, short):
                    imported.append((short, branch))
                    baseline[short] = line
                    print(f"  ++  {line}   [branch {branch}] (imported)")
                else:
                    print(f"  !!  {short}  [branch {branch}] import failed")
        finally:
            release_worktree(root, worktree, tmp)

    print()
    if args.dry_run:
        print(f"scanned {len(branches)} branch(es): {len(found)} branch-hidden todo(s) found.")
    else:
        print(
            f"scanned {len(branches)} branch(es): "
            f"{len(imported)} branch-hidden todo(s) imported into {root}/.todo."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

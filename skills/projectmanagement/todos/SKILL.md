---
name: todos
description: >-
  Branch-bound todo task tickets managed through the todo.py CLI (one ticket
  per git branch; stored in ~/.todo/sqlite.db by default). TRIGGER: the user
  says "TODO", "todo", "ticket", "branch task", or asks to track/manage task
  state -- invoke immediately. Route ALL ticket access through todo.py; never
  read or write TODO.json directly or query sqlite by hand. The full workflow,
  CLI, and schema live in this skill body and load only when triggered.
disable-model-invocation: false
---

# Todo tickets

status: living document

Associative memory for pruned contexts: a task ticket that lives with a git
branch. One branch carries **zero or one** ticket in sqlite (default ~/.todo/sqlite.db). Legacy TODO.json is import-only.

## Definitions

- **`gitroot`:** `git rev-parse --show-toplevel` -- the current working tree
  (a linked worktree, when you are in one). Used for git *operations*.
- **`main checkout root`:** the repo's PRIMARY working tree (first entry of
  `git worktree list`). This is the **storage anchor** -- the todo store lives at
  `<main-checkout-root>/.todo/`, so all worktrees of a repo share one store. Git
  ops still run in `gitroot` (the current worktree); only the store anchors here.
- **CWD is a TODO branch:** the current directory is in a git repo and its
  `gitroot` holds a `TODO.json`.
- **Repo root:** the local directory where a repo is checked out (e.g.
  `$(gitroot)`, `~/Projects/opportunity`, `~/github.com/jovlinger/util`). A
  GitHub repo can be cloned several times on one or many machines, so the *same*
  todo may exist in several checkouts at once. The repo root is what
  disambiguates **which** checkout a branch lives in.
- **FQT (fully-qualified todo):** `repo-root + todo_id`. The full git branch
  name is an artifact of git storage, not part of identity -- but since we do
  not plan to migrate off git, `repo-root + branch-name` is equally accepted,
  and is the fallback for todos written sloppily on `dev`/`master`. The branch
  name is derivable from the todo Id.

**Selecting a repo:** `todo.py` takes the repo root from the **current
directory's `gitroot`** and **hard-errors if CWD is not a git repo**. There is
**no `--repo` flag** -- `cd` into the target repo (or worktree) before invoking.
Use `git worktree list` to find other checkouts.

## Multi-agent model

Atomic edits will not be needed due to agent == actor model. One agent owns the
branch. Inter-agent communication is per message send via git.

Verified conditional notification channel: when a parent chat session launches
Cursor background subagents for subtodos, the Cursor harness can deliver
subagent-completion notifications back into the same parent chat. The parent can
use that chat session as a shared notification channel, then inspect the child
artifact/worktree and update the parent through `todo.py merge-subtodo`. This is
conditional on the subtodos being launched under the same orchestrating
chat/session and the harness surfacing completion events there; it is not a
portable git-level signal.

Portable fallback remains polling: `todo.py wait-for <id>...` polls child todo
state until each reaches `done`, then the parent runs `merge-subtodo` or
`wait-and-merge`.

### Recursive completion (subtodos)

The **goal of a parent ticket is to finish by doing local work and merging
subtodos.** Treat subtodos like function calls: each child must **return** before
the parent can complete. Setting a child to `done` without `merge-subtodo` on
the parent is an incomplete call -- same as forgetting to await a promise.

**Invariants (hard rules for agents):**

| Rule | Meaning |
|------|---------|
| Every subtodo must terminate | Each child reaches `done`, `merged`, or **surfaces** via `userneeded` / `stopped` (analogous to raising -- propagate blockers to the user; do not swallow them). |
| No silent skips | Do not mark the parent `done` while any subtodo is still `init` or `working`, or `done` but not yet `merge-subtodo`'d on the parent. |
| Merge is bookkeeping + git | After the child's git branch is merged (or absorbed), run `merge-subtodo <child-id>` on the **parent** branch so `Subtodos[].State` becomes `merged`. |
| Parent synthesis last | Parent `done` only after all subtodos are `merged` (or explicitly waived by the user). |

**Normal loop:**

1. Parent `working`; file subtodos with `add-subtodo` (each records a `start_subtodo` item and advances the parent cursor).
2. Per child (often one subagent each): on the child branch run the lifecycle loop (`set-state working`, poll and work items to `is-done`, `set-state done`).
3. Parent: `wait-for` / `wait-and-merge` (or `merge-subtodo` each) until every child is `merged` on the parent record.
4. Parent works any remaining synthesis WorkItems to `is-done`, then `set-state done`.

**Surfacing blockers:** If a child cannot finish without the user, `set-state userneeded --note=...` on that child, then set parent `userneeded` with which child blocked. Never leave a child in `init`/`working` indefinitely without escalating.

**Anti-patterns (do not do this):**

- Landing all code on the parent branch while child branches stay `init`.
- Marking children `done` from the parent checkout without working the child branch.
- Marking parent `done` when `todo.py jq self '.Subtodos[].State'` still shows `init` or `done` (unmerged).

### Working subtodos: sequential stack order is the default

When told to "work" a todo with subtodos, **default to working them sequentially,
in one context, in stack order -- do NOT fan out parallel subagents.** The tool
exists so a single agent can work a subtodo stack one frame at a time while the
**todo record (not the chat) holds the durable state**, keeping your context
small. `execution.mode: "parallel"` means children *may* run concurrently, not
that you *should* fan out. Spawn parallel subagents ONLY when the user explicitly
asks, or for genuinely independent context-heavy fact-finding domains (see
Context-scoped subtodos). When unsure, work sequentially.

Between subtodos, use Claude Code's **`/rewind`** to shed the finished subtodo's
context before starting the next:

1. Work the top subtodo to `done` and `merge-subtodo` it on the parent. Its
   result is now durable in git + the todo record.
2. **`/rewind` the conversation** (conversation, not code) back to before that
   subtodo's context was loaded. The chat forgets the subtodo; the todo remembers
   it. Committed work is untouched -- `/rewind` never rewrites git history.
3. Reload the next frame with `todo.py prompt <id>` / `todo.py read` and work it
   the same way.

This works because the todo IS the memory: each subtodo's WHY (its `Parent` chain
via `prompt`) and WHAT (its committed `WorkItems` trail) reconstruct from the
record, so dropping the chat context loses nothing. A deep stack is thus worked
frame-by-frame with a clean context at each frame, instead of one bloated window
or an uncontrolled parallel fan-out.

### Parent linkage and startup context (`prompt`)

Every child records its parent(s) so a fresh agent with **zero context** can
recover WHY it is doing the work. The link is the child's `Parent` field -- a
**list** of `{Id, Branch}` refs:

- `add-subtodo` sets it (element 0 = the structural/fork parent) and also
  registers the child on the parent side (`Subtodos`) as a **tracked, mergeable**
  subtodo -- the full merge-bookkeeping lifecycle.
- `todo.py init --parent <id>` (repeatable) records the child's `Parent` ref
  **and** writes a follow-only **INFO back-link** into the parent's `Subtodos`
  (`State: "INFO"`), so the link is navigable both ways (HATEOAS) without the
  parent taking on any merge obligation. Use it to hang a fresh todo off an
  existing one (even an old, unrelated todo) for context. The INFO link is *not*
  a tracked subtodo: it is excluded from merge-completeness, the child sets it
  once at creation and never updates it, and `doctor` refreshes its best-effort
  `Summary` when sweeping. For a real subtodo the parent must merge, use
  `add-subtodo` instead.

INFO back-links are best-effort and same-repo (a write keys by the current
repo). A child created before this behavior, or one whose parent lives in
another repo at creation time, is healed by `doctor` (which re-establishes the
back-link from the child's `Parent` ref) the next time it runs in the parent's
repo.

**First thing a working agent should do:** run `todo.py prompt <id>` (default
`self`). It walks the `Parent` chain up and concatenates each todo's
Summary/Body -- farthest ancestor first, this todo last -- into one startup
prompt, so you read the overarching WHY down to your specific WHAT before
touching code. It is read-only and resolves parents from the db without checking
out branches; an unresolvable parent is noted, not fatal.

### Context-scoped subtodos (local subagents)

**WorkItems** are ordered steps on the **parent** branch -- same checkout, same
conversation context. **Subtodos** are separate branches with their own
`TODO.json`, meant for work that should not share one bloated context window.

Prefer subtodos (via `add-subtodo`, often driven by **local subagents** in the
same parent chat) when:

| Signal | Why subtodos |
|--------|----------------|
| Independent fact-finding domains | Each domain pulls in unrelated files, CLI help, and endpoint probes; keeping it on the parent pollutes synthesis. |
| Scoped research before a merge doc | Parent AC is a summary matrix; children produce per-area notes or small commits the parent merges. |
| Parallel exploration | DMZ `manage`/`/version`, Pi Zero compose deploy, Pico2W UF2 limits, ESP32 flash path can run concurrently on child branches. |
| Child artifact is branch-bound | Findings land as a child commit or notes fragment on the child branch; parent reads via git merge or `todo.py read <child-id>`, not chat memory. |

**Typical pattern (planning / OTA / architecture tickets):**

1. Parent ticket: summary, AC, WorkItems for synthesis and final doc.
2. `add-subtodo` per domain (example children: "DMZ manage and /version inventory",
   "Pico2W upgrade constraints", "ESP32-S3 deploy feasibility").
3. Launch a **local subagent per child** (same session; user may say "local agents
   only" -- still use subtodos for context isolation without cloud-only assumptions).
4. Each child: `working` -> narrow research -> `done` with a committed artifact.
5. Parent: `wait-for` / `wait-and-merge` until every child is **`merged`** on the
   parent (not merely `done` on the child branch), then synthesis WorkItems, then
   parent `done`.

Do **not** file subtodos when the work is a short linear edit, a single subsystem,
or when child branches would be empty shells with no distinct artifact -- use
parent WorkItems instead.

**v1 mainline (what a normal run uses):** find the repo root, create one ticket
if none exists, work it `init -> working -> done`, read and patch fields with
`todo.py`. Use subtodos when the ticket spans multiple independent research
domains (above). Stacks across branches, dependency graphs, and embeddings beyond
that are **deferred** and listed at the bottom.

## Storage (sqlite default)

Todo directory resolution (once per `todo.py` invocation; no mixing paths). The
repo anchor is the repo's **MAIN checkout root** -- the primary working tree, NOT
the current linked worktree -- so every worktree of a repo shares ONE store in the
core checkout. (`git worktree list` lists the main worktree first; bare/no-checkout
hosting is out of scope.)

1. `$TODO_DIR` when set and it contains `sqlite.db`
2. `<main-checkout-root>/.todo/` when that contains `sqlite.db`
3. `$HOME/.todo/` when that contains `sqlite.db`

If none exist, create under the first applicable default: `$TODO_DIR`, else
`<main-checkout-root>/.todo/`, else `$HOME/.todo/`. Db and worktrees both live
under the chosen directory. Note: the storage anchor is the main checkout root;
git *operations* (branch create/checkout/commit) still happen in the current
worktree.

| Item | Location | Notes |
|------|----------|-------|
| Tickets | `<todo-dir>/sqlite.db` | One row per (repo_path, branch); `todo.py ls` lists them |
| Embeddings | sqlite embeddings table | Cheap (hash) on write; others backfilled on search |
| Worktrees | `<todo-dir>/worktrees/` | Nested by repo path |
| Legacy JSON | git TODO.json | Import only: todo.py import-json |

Set TODO_USE_JSON=1 for legacy file mode. Search embedders: `todo.py search
--embedder` (comma list; default all non-hidden; see `todo.py embedders`).

## CLI (`todo.py`)

AWS-style subcommands live beside this skill as
[`todo.py`](todo.py). Demo API first; efficiency is not the goal.

`todo.py` is **mechanism** only: it stores and mutates todos. *Policy* -- how
to size, sequence, and refine work into WorkItems -- lives in `frequentcommits`.
Do not push sizing or sequencing rules into the tool.

All `TODO.json` access goes through this CLI, even if the requested operation is
"just print it" or "check whether it exists." Do not use `cat`, `jq`,
`ReadFile`, `git show`, shell tests, or ad hoc JSON parsing against `TODO.json`
directly. Treat `TODO.json` as a temporary storage implementation hidden behind
the `todo.py` interface.

| Command | Status | Behavior |
|---------|--------|----------|
| `todo.py mint` | implemented | Mint a fresh ticket `Id` (uuid1 -> SHA-256 of its raw bytes), collision-checked across the repo; print the 64-hex Id |
| `todo.py read <selector>` | implemented | Locate the branch (or worktree) whose `TODO.json` matches `<selector>` and print the ticket JSON. Id selectors are any **4+ hex unambiguous prefix**, or the full digest. `curr`/`self` resolve to the checked-out branch's todo, even when the branch name does not contain the Id. Resolution scans the sqlite `tickets` table directly (cross-repo, no catalog); it falls back to a current-repo ref scan only when sqlite has no hit. Local-first: remote fetch is feature-flagged off (`FETCH_ENABLED`) |
| `todo.py search <query>` | implemented | Vector + lexical ticket search (-n limit); `--embedder` comma list (default all non-hidden), `--dry-run` |
| `todo.py prompt [<selector>]` | implemented | Concatenate a todo and its `Parent` chain (Summary/Body) into one startup prompt, farthest ancestor first, target last -- zero-context agent reads WHY down to WHAT. Read-only; default `self` |
| `todo.py embedders` | implemented | List selectable search embedders (non-hidden) with cheap/expensive |
| `todo.py import-json` | implemented | Migrate legacy JSON: --from-json PATH or --scan-refs |
| `todo.py ls [-t]` | implemented | Print `<id[0:8]>  <summary>` for every ticket in sqlite -- where-to-find-it only; use `read <id>` for content. Default order is insertion order; `-t` sorts by last-update time, most recent first, like shell `ls -t` |
| `todo.py get-json-path <selector> <path>` | implemented | Low-level path read. Prints one value from a selected todo as JSON. `<path>` is the internal dot-path syntax, e.g. `Body.raw` or `WorkItems.0.summary`. |
| `todo.py set-json-path <selector> <path> [--file <path>]` | implemented | Low-level path write. Sets one JSON path to a value read as JSON from `--file` or stdin. Checks out the target branch for a non-self selector; `--stay` to remain; commits by default. The general way to replace `WorkItems` or seed a whole plan. |
| `todo.py jq <selector> <jq-filter>` | implemented | Read-only jq-compatible projection. Shells out to `jq` internally unless/until a 100% compatible Python jq library is chosen. This keeps callers behind `todo.py` while preserving jq filter semantics. |
| `todo.py init --summary=...` | implemented | Mint Id (or `--id`), create local branch, write ticket to sqlite, empty commit. Captures the branch's initial sha into `BaseSha` (invariant #5). Refuses when current branch already has a ticket. `--parent <id>` (repeatable) records a parent/context reference on the new todo and writes a follow-only `INFO` back-link into each parent's `Subtodos` (bidirectional but no merge obligation; use `add-subtodo` for the tracked, mergeable lifecycle). `--agent-type` / `--session-id` (or `$TODO_AGENT_TYPE` / `$TODO_SESSION_ID`) record the creating agent in the ticket's `Agent` field |
| `todo.py add-subtodo --from-json=...` | implemented | From a parent todo branch: create child branch + `TODO.json` (captures child `BaseSha`), commit, return to parent, register in `Subtodos`. Completes the parent's cursor work item as a typed `start_subtodo` done item and advances the cursor |
| `todo.py set-state <state>` | implemented | Sugar for setting `State` to a single-key object plus path triggers. Valid states are `init`, `working`, `done`, `merged`, `userneeded`, `stopped`; commit by default. `--actual-summary=...` records how the work actually panned out into `ActualSummary` (used later as the merge message) |
| `todo.py merge-subtodo <id>` | implemented | After child is `done`: checkout child branch, set `merged`, commit; update parent `Subtodos[].State` to `merged`. Records a typed `merge_subtodo` done item on the parent's cursor with the merge sha and advances the cursor. The merge commit subject and work item summary come from the child's `ActualSummary` (falling back to `Summary.raw`) |
| `todo.py set --summary=... --body=... --ac=...` | implemented | Patch `Summary.raw`, `Body.raw`, and/or `AC` on the current branch's todo |
| `todo.py work-item-add --summary=...` | implemented | Append a not-done `task` work item (`{kind:"task", summary, done:false}`) to `WorkItems` |
| `todo.py work-item-done [-m MSG] [--sha SHA] [--summary S]` | implemented | Complete the cursor (first not-done) item as a typed `code` item and advance the cursor. Post-condition: branch fully committed. Dirty tree: commits `git add -A` (message = `-m` or the work item summary), records new HEAD sha. Clean tree: records HEAD, or a `--sha` that must equal HEAD (mismatch exits 1). Adds no bookkeeping commit, so the sha stays branch HEAD (#6). Stores the full commit message on the node as `message` so the WorkItems trail records what actually changed -- pass a descriptive `-m` (outcome + files/tests added) |
| `todo.py work-item-read [<selector>]` | implemented | Print the cursor work item (first not-done), its index, whether the todo is done, and a `next` object -- the deterministic mechanical command to advance the loop (`{action, command}`), including the finish sequence when done. `next` is a mechanism hint, not policy; a plain task defaults to `work-item-done` but may instead be split or turned into a subtodo per the dispatch table |
| `todo.py work-item-insert --summary=...` | implemented | Insert a not-done `task` at the cursor so it becomes current, pushing the frontier down (used to explode a step into finer steps); appends when there is no open item |
| `todo.py work-item-replace --summary=...` | implemented | Rewrite the cursor task's freetext summary, leaving it not-done |
| `todo.py work-item-delete` | implemented | Delete the cursor (not-done) work item |
| `todo.py is-done [<selector>]` | implemented | Report whether the todo has no not-yet-done work items (#7); exits 0 when done, 1 when not |
| `todo.py last-sha [<selector>]` | implemented | Print the sha of the last work item, which is the last commit on the branch (#6) |
| `todo.py wait-for <id>...` | implemented | Poll selected child todos until they reach a target state, default `done`, without direct file reads. Initial implementation polls through todo selectors; better signaling can follow real usage. |
| `todo.py wait-and-merge <subtodo-id>...` | implemented | Poll child todos until `done`, then run merge bookkeeping for each child. |
| `todo.py doctor [<selector>] [--all] [--dry-run]` | implemented | Audit schema, references, wait graph, and the WorkItem invariants (#1/#3/#6/#7), **and repair parent back-links**: for each `Parent` ref on the audited todo, re-establish a follow-only `INFO` back-link in the parent's `Subtodos` (best-effort, same-repo, sqlite only). Repair runs by default; `--dry-run` reports intended repairs without writing; `--all` sweeps the whole corpus instead of one selector. Two finding tiers: hard `findings` (fail, exit 1) for shape violations; soft `warnings` (never fail) for checks needing an absent subbranch or other repo |
| `todo.py log [<selector>]` | implemented | Render the ticket graph (the `Subtodos` tree) for `<selector>` (default `self`; `self`/`curr` or a 4+ hex Id prefix) in git-log `--graph --oneline` style: `* <Id[0:8]> <summary>  [<state>]` with `\|` rails. `--all` renders every root as a forest; `-n N` caps lines; `-v` lists each ticket's branch commits (its frequentcommit trail); `-t` adds timestamps (ticket update time on nodes, commit date on the `-v` lines). Graph structure is from `TODO.json` via todo.py's readers; only `-v`'s commit lines read git. Output truncates to terminal width on a TTY, full when piped. |
| `todo.py new --summary=... --body=...` | planned | alias for `init` with optional JSON seed |

Run from inside the target repo (`cd` there first; there is no `--repo` flag --
repo root is the current directory's `gitroot`):

```bash
chmod +x skills/projectmanagement/todos/todo.py   # once
skills/projectmanagement/todos/todo.py read 8f3a2c1d
skills/projectmanagement/todos/todo.py read self
```

## Selectors and path primitives

Selectors are the public way to name a todo. Implemented selectors are full `Id`,
unambiguous 4+ hex `Id` prefixes, and current-branch aliases:

| Selector | Meaning |
|----------|---------|
| `self` | Resolve the todo for the checked-out branch. |
| `curr` | Alias for `self`. |

`self`/`curr` resolution must not depend only on an Id prefix in the branch
name. Deconstruct the current branch and combine it with repo identity plus the
repo's main branch name; that tuple is unique enough to select the branch-bound
todo even for branches that do not contain the ticket Id.

The lowest-level API should be:

| Primitive | Behavior |
|-----------|----------|
| `read <selector>` | Print the whole todo. |
| `get-json-path <selector> <path>` | Print one internal dot-path value as JSON. |
| `set-json-path <selector> <path> [--file <path>]` | Set one internal dot-path value from JSON on stdin or `--file`. |
| `jq <selector> <filter>` | Run a jq filter against the selected todo and print the result. |

Higher-level commands are special syntax for these primitives, plus triggers.
Triggers fire by changed path, not by command name, so `set-state done` and
`set-json-path self State` (with `{"done": {}}` on stdin) share the same
downstream behavior.

## Placement and branch rule

| Rule | Value |
|------|-------|
| Storage | `<main-checkout-root>/.todo/sqlite.db` by (repo_path, branch); repo_path is the main checkout, not a worktree |
| Per branch | 0 or 1 ticket |
| Legacy file | TODO.json -- import only; doctor warns |
| Conflict | If `TODO.json` already exists on the branch, **resume or finish** it; do not create a second ticket, rename, or use subdirs |

Typical pairing: create the branch when you open the ticket; set `Branch` and
`Scope.branch` at that point (the branch may exist only locally until pushed).

**Lifetime:** `TODO.json` lives with the branch. Cleanup, archival, and
post-`done` moves are out of scope -- do not delete or relocate the file as part
of this workflow unless the user explicitly asks.

## Worktree placement

**Worktrees are ephemeral. The durable asset is the repo and the TODO's
branch.** The `TODO.json` lives on the branch, the branch lives in the repo (and
is pushed to the remote) -- that pair is the identity and the thing that
survives. A worktree is just a disposable checkout used to work that branch;
create and delete them freely, and never treat a worktree path as where a todo
"lives." Find todos by repo + branch (`todo.py ls` / `todo.py read <id>` query
sqlite directly); use `git worktree list` only to locate a branch's current
checkout when one exists.

### Subtodo worktree lifecycle (open on entry, tear down on last commit)

A **subtodo is worked in its own dedicated git worktree**, so parent and siblings
never share a checkout:

- **On entry** (an agent begins working a subtodo -- typically `set-state
  working`): create a fresh worktree for the subtodo's branch under the placement
  convention below (`git worktree add <todo-dir>/worktrees/<repo-path>/<branch>
  <branch>`) and `cd` into it. Reuse an existing worktree for that branch if
  `git worktree list` already shows one; never move it.
- **On last commit** (the subtodo's final commit is in -- `is-done` is true and its
  `set-state done` commit has landed): tear the worktree down (`cd` out, then
  `git worktree remove <path>`). Teardown removes only the *checkout*; the branch
  and its commits survive for the parent's `merge-subtodo`. If the tree is dirty,
  the subtodo is not actually done -- finish or surface it before removing.

The branch is the durable asset; the worktree is scratch space that exists only
for the span from entry to last commit.

A todo's working tree may live in a dedicated git worktree rather than the main
checkout. **Existing worktrees are found with `git worktree list` and are never
moved.** Only *new* worktrees follow the placement convention below; the path is
never passed on the command line -- it is a creation convention, not a lookup
key.

New worktrees go under todo_db.worktrees_dir() (`<todo-dir>/worktrees/`), nested by the repo's full path with the branch as the
leaf:

```
<todo-dir>/worktrees/<repo-path>/<branch>
# e.g. ~/.todo/worktrees/github.com/jovlinger/util/my-branch
#      <main-checkout-root>/.todo/worktrees/github.com/jovlinger/configfiles/todo-webui
```

- `<repo-path>` mirrors the repo's canonical path (host/org/repo) as real nested
  directories; snake-case a single segment only if it would otherwise collide.
- `<branch>` is the branch name with any `/` sanitized.
- `TODO.json` lives at the worktree root, exactly as on a normal branch; `read`
  discovers worktree tickets (reported as `worktree:<branch>`).

```bash
git worktree add ~/.todo/worktrees/<repo-path>/<branch> <branch>
```

`todo.py` worktree automation is future; for now this is a manual convention,
and discovery relies on `git worktree list`.

## Before you start

```bash
git rev-parse --show-toplevel        # confirm repo root; cwd should be here
todo.py init --summary="..."         # refuses if current branch already has a ticket
todo.py init --summary="..." --parent <id>   # hang a new todo off an existing one for context
todo.py read <known-id-prefix>        # load a known ticket; do not read TODO.json directly
todo.py read self                     # current-branch lookup
todo.py prompt self                   # WHY->WHAT startup context: self + its Parent chain
```

Use `init`'s refusal as the guard against creating a second ticket on the branch,
or use `read self` / `read curr` to load the current branch's ticket.

## JSON access

- Keep `TODO.json` **well-formed JSON** at all times by using `todo.py` for every
  read and write. The CLI owns parsing, validation, normalization, timestamps,
  branch checkout, and commits.
- **Never** read field values by eyeballing JSON pasted into chat, direct file
  reads, `cat`, `jq`, `git show`, or shell tests. Even read-only stdout display
  is `todo.py read <id-prefix>`.
- **Never** hand-edit an existing `TODO.json` in the model context. Use `todo.py
  set`, `todo.py set-state`, work-item commands, `add-subtodo`, `merge-subtodo`,
  or `todo.py set-json-path <id> <jsonpath>` (value as JSON on stdin or `--file`).
- Temporary seed JSON files passed to `--from-json` or `set-json-path --file` are
  inputs to the CLI, not direct `TODO.json` access. They may be authored as
  ordinary files, then consumed by `todo.py`.

```bash
# read the full todo JSON
todo.py read 8f3a2c1d

# read one field
todo.py get-json-path self Summary.raw

# jq-compatible read projection (todo.py shells out to jq internally)
todo.py jq self '.Id, (.State | keys[0]), .Summary.raw'

# patch simple fields on the current branch
todo.py set --ac="new criteria"

# patch any JSON path on any todo by id; value is JSON read from stdin (or --file)
printf '%s' '"new body"' | todo.py set-json-path 8f3a2c1d Body.raw

# transition state; todo.py updates update_dt and commits by default
todo.py set-state working --owner=agent
```

## Id minting

`Id` is **not** the raw UUID string: it is the SHA-256 (64-hex) of a **uuid1**'s
raw bytes -- the one fixed version, mixing host MAC, time, and a random clock
sequence. The full digest is the canonical `Id`; `Id[0:8]` is the git-like short
id on the branch (8-or-more, your call). The tool owns minting and the collision
search -- do not hand-roll it:

```bash
TODO=skills/projectmanagement/todos/todo.py
ID=$("$TODO" mint)        # collision-checked across the repo
# branch prefix is ${ID:0:8}
```

Store the full `Id`; the source UUID is ephemeral entropy. `mint` regens on the
(rare) 8-hex prefix clash, and its local branch+worktree search can widen to a
global search later without changing how you call it. To reference a ticket
later, any **4+ hex unambiguous prefix** resolves via `todo.py read`.

## Record shape

One ticket per `TODO.json`: a single top-level object. Field names use the
user's casing until a formal schema lands.

Schema direction: define the allowed top-level fields and reject unknown fields
in `doctor`. Optional fields are deleted by setting them to `null`; do not add a
separate unset/delete operation unless repeated use shows `null` is insufficient.

### Identity and branch

| Field | Type | Behavior |
|-------|------|----------|
| `Id` | string | SHA-256 hex (64 chars) of a mint UUID; see Id minting. |
| `Branch` | string | Best-effort label, constructed once: `(Id[0:8] + "-" + kebab(big words of Summary.raw))[:32]`. Drop obvious stopwords; do not agonize. May exist only locally. |
| `create_dt` | string (RFC3339 `Z`) | Immutable creation time. |
| `update_dt` | string (RFC3339 `Z`) | Bump on **every** successful write. |

### State

`State` is an object with **exactly one** key: the state name. Optional fields
live in that state's value object. Mainline flow is `init -> working -> done`; subtodos the parent merges go
`done -> merged`. `userneeded` and `stopped` are the interrupts a normal run may hit.

| State | Value shape | Meaning |
|-------|-------------|---------|
| `init` | `{}` | Ticket filed; not yet started. |
| `working` | `{ "owner"?: string, "expire"?: rfc3339 }` | Active work. (`owner`/`expire` only matter for future multi-owner handoff; omit on a single-agent run.) |
| `userneeded` | `{ "note"?: string }` | Agent blocked; needs user input. |
| `stopped` | `{ "note"?: string }` | User override halt. |
| `done` | `{ "last_commit"?: string }` | Complete on the ticket branch; record last commit message if useful. |
| `merged` | `{ "merged_into"?: string, "last_commit"?: string }` | Parent absorbed this branch; written on the **child** todo after merge. Parent `Subtodos[].State` becomes `merged`. |
| `waiting` | (deferred) | Blocked on subtodos -- see Deferred. |
| `N/a` | `{}` | Non-work associative item (a stored fact, not a task). |

Always patch `State` and `update_dt` together.

### Scope

Where the ticket applies. Set at least one locator.

| Key | Notes |
|-----|-------|
| `git_url` | Remote or canonical git URL. |
| `path_to_project` | Local path alternative to `git_url`. |
| `path_from_root` | Path inside the repo. |
| `branch` | Requires `git_url` when set. |

### Summary, Body, AC

| Field | Type | Behavior |
|-------|------|----------|
| `Summary` | object | `{ "raw": "<human title>" }`. Optional embedding keys may be added later for recall (vector format deferred). |
| `Body` | object | `{ "raw": "<description>" }`. Same optional-embedding pattern. |
| `AC` | string | Acceptance criteria, concrete enough to agree on "done". |
| `ActualSummary` | string (optional) | How the work actually panned out (vs the planned `Summary`). Written at finish via `set-state done --actual-summary=...`; when this todo is later merged into a parent, `merge-subtodo` reuses it as the merge commit subject and the parent's `merge_subtodo` work item summary, falling back to `Summary.raw` when absent. |

`Summary.raw` and `Body.raw` are always present; embedding keys are optional
enrichments, omitted on first write and backfilled later if ever.
`ActualSummary` is optional and omitted until the work is done.

### WorkItems: invariants and the cursor

`WorkItems` is the ordered work plan for a todo. Each item is either a not-done
`task` (freetext, may list not-yet-started subtasks in prose) or one of three
typed **done** kinds, each produced by the command that performs that work:

| kind | fields | produced by |
| --- | --- | --- |
| `task` | `summary`, `done:false` | `work-item-add` / `work-item-insert` (not done) |
| `code` | `summary`, `sha`, `message`, `done:true` | `work-item-done` (local coding) |
| `merge_subtodo` | `summary`, `subtodo_id`, `sha`, `done:true` | `merge-subtodo` |
| `start_subtodo` | `summary`, `subtodo_id`, `done:true` (no sha) | `add-subtodo` |

`summary` is the high-level step description (carried over from the cursor task). `message`
on a `code` item is the **full commit message** recorded at `sha` (from `work-item-done`'s
`-m`, or the existing HEAD commit's message on a clean tree). This makes the WorkItems trail
**self-describing**: walking the nodes alone answers "what did each step change -- were tests
added?" without resolving shas to git. So `-m` MUST state the concrete outcome (files/tests
added, with paths), not a vague label -- it is the durable per-step ledger entry, distinct from
the task `summary`. Note `work-item-done` completes the **cursor** (first not-done item), so its
message attaches to whatever item is at the cursor -- complete items in cursor order or the
message lands on the wrong node.

The **cursor** is the first not-done item (derived, not stored). Work proceeds
by completing the cursor and advancing; the cursor index never decreases though
the list may grow (e.g. `work-item-insert` explodes one step into several). The
invariants the tool guarantees and `doctor` enforces:

1. A done item is a `start_subtodo`, or carries a `sha` (a `code` or
   `merge_subtodo` commit) with a high-level description.
2. A not-done item is freetext (a task or a list of not-yet-started subtasks).
3. Done items form a prefix; the cursor moves monotonically down.
5. `BaseSha` records the branch's initial sha, captured at branch creation.
6. The last item cannot be `start_subtodo` -- it must be a `code`/`merge`
   commit, so the last item's sha (`last-sha`) is the branch's last commit.
7. A todo `is-done` when it has no not-yet-done items.

`is-done` and `last-sha` expose these as subcommands. `doctor` reports shape
violations as hard `findings` and checks that need an absent subbranch/other
repo (unresolvable sha or subtodo_id) as soft `warnings`.

Larger work may add an `execution` object to make ordering and parallelism
explicit without inventing a scheduler.

Common shapes:

```json
{
  "id": "wi-001",
  "summary": "Start subtodo abc12345: gather external stimuli",
  "done": false,
  "execution": {
    "mode": "parallel",
    "group": "foundation",
    "primitive": "add-subtodo",
    "subtodo_id": "abc12345..."
  }
}
```

```json
{
  "id": "wi-003",
  "summary": "Wait-and-merge foundation subtodos",
  "done": false,
  "execution": {
    "mode": "barrier",
    "primitive": "wait-and-merge",
    "wait_for": ["abc12345...", "def67890..."]
  }
}
```

Use `execution.mode = "parallel"` for WorkItems that can begin independently
(for example, CPU-delayed loads, evidence extraction, or test-structure
research). When the parallel work is **context-heavy fact-finding** across
unrelated subsystems, prefer **subtodos + local subagents** (see
Context-scoped subtodos) instead of many parent WorkItems in one chat. Follow
parallel children with a barrier WorkItem when later work needs all results. The
first `wait-and-merge` implementation may simply poll `todo.py read <id>` until
each child reaches `done`, then run `todo.py merge-subtodo <id>` for each child.

Notification remains deliberately primitive at first: poll via `todo.py`.
Consider better signals only after the barrier primitive has been used enough to
show what is actually missing.

### Wait and signal sketch

`wait-for` and `wait-and-merge` are coordination primitives for parent/child
todos. The parent waits on child state transitions; the child signals by calling
`set-state` through the normal CLI.

Initial implementation:

1. Parent records a barrier WorkItem with `execution.primitive =
   "wait-and-merge"` and `wait_for` child Ids.
2. Child runs its lifecycle loop to `is-done` and reaches `set-state done`.
3. Parent `todo.py wait-for <child>...` polls `todo.py get-json-path <child> State`
   until every child reaches `done`.
4. Parent `todo.py wait-and-merge <child>...` runs `merge-subtodo` for each done
   child and marks the barrier WorkItem done.

Possible later signal channels:

- **Parent chat notifications:** valid only when Cursor background subagents
  were launched by the same parent chat and completion events return there.
- **Git polling:** parent watches child refs and reads state through `todo.py`;
  portable, simple, and probably good enough.
- **Named files in `/tmp`:** possible semaphore implementation, but process-local
  and non-portable across machines. Do not choose this before git polling fails
  in real use.
- **Git hooks:** too magical for v1. Avoid coupling child `set-state` to
  repository hooks unless there is a concrete repeated need.

### Editing the work plan

The cursor commands cover the common story, all acting on the current (first
not-done) item: `work-item-add` (append a task), `work-item-insert` (split the
current step, becoming the new cursor), `work-item-replace` (reword the cursor
task), `work-item-delete` (drop it), and `work-item-read` (inspect it). Done
items are the committed history of the todo -- edit the not-done frontier, never
the done prefix.

For a wholesale replan use `set-json-path <id> WorkItems --file <array.json>` (or
pipe the JSON array via stdin); for a precise edit deep inside one item use
`set-json-path <id> WorkItems.<n>.summary`. `doctor` will flag a plan that breaks
the invariants (a done item out of the prefix, a code/merge item missing its
sha, a `start_subtodo` left as the last item).

### Worktree operations

Manual worktrees are enough until a workflow requires automation. A future
`worktree add/list/remove` family is justified when the agent needs to run parent
and child todos concurrently in separate checkouts, or when a parent needs to
enumerate child worktrees without relying on chat memory. If there is no concrete
parallel-checkout use case, keep worktree creation/listing manual.

## Doctor checks

`todo.py doctor [<selector>]` audits and, by default, repairs. It re-establishes
follow-only `INFO` parent back-links from the audited todo's `Parent` refs
(best-effort, same-repo, sqlite only); `--dry-run` makes it report-only and
`--all` sweeps the whole corpus. Checks:

- Selector resolution: ids are unambiguous; `self`/`curr` resolves to exactly one
  branch-bound todo.
- Schema: allowed top-level fields only; required fields present; optional fields
  are either valid values or `null`.
- State: `State` has exactly one key and the state name is valid.
- References: `Parent` (a list of `{Id, Branch}` refs) and `Subtodos` point to existing todos when discoverable.
- Dependency graph: waiting/barrier relationships are acyclic.
- Wait sanity: a parent is not waiting on itself, a missing child, or a child in
  an impossible terminal state.
- Subtodo merge completeness: every *tracked* `Subtodos[]` entry should be
  `merged` (or waived by user) before parent `done`. Any child not `merged`
  (including one spawned via `start_subtodo` that terminated
  `userneeded`/`stopped`) is a soft **warning** while the parent is still open,
  and a hard **finding** once the parent is `done`/`merged` -- a spawn without a
  merge cannot survive parent completion. Follow-only `INFO` back-links are
  excluded (they carry no merge obligation).
- WorkItem invariants (#1/#3/#6/#7): valid kinds; done items form a prefix; a
  `code`/`merge_subtodo` item carries a sha; a done todo does not end in
  `start_subtodo`.

Findings come in two tiers: hard **findings** fail doctor (exit 1); soft
**warnings** never fail it. Checks that need an absent subbranch or another repo
-- an unresolvable sha or `subtodo_id` -- are warnings, so transitional and
cross-repo todos (where not every subbranch is available) do not hard-fail.

## Todo lifecycle (poll the tool for the next step)

This is the authoritative lifecycle. **The todo tool carries the process
weight**: the agent does not track "where am I" in its head -- it polls the tool
for the next work item and acts on what it gets back. One todo == one branch;
its lifetime matches the branch's (invariant #4).

**Create.** On the intended branch, `todo.py init --summary=... --body=...
--ac=...` mints the Id, creates the branch, records `BaseSha` (invariant #5),
and stores the ticket. Plan the work as WorkItems with `work-item-add
--summary=...`; keep the **head of the list small enough to be one trackable
unit** (see `frequentcommits`).

**Poll.** Ask the tool what to do next, then act, then poll again:

```bash
todo.py work-item-read      # the cursor + a `next` hint, or the finish action when done
todo.py is-done             # exit 0 when nothing is left, 1 otherwise
```

`work-item-read` emits a `next` object -- `{action, command}` -- naming the
deterministic mechanical command to advance the loop (e.g. `work-item-done`, or
the finish sequence when `is_done`). It is a mechanism hint the tool can compute
from the cursor; the rows below are the authoritative dispatch, and you still
override `next` when policy says a plain task should become a subtodo or be
split.

The cursor only moves forward. Each row below advances it by recording a typed
done item -- the tool guarantees the shape and captures the sha:

| The cursor item is... | Do | Tool records |
|------------------------|----|--------------|
| a subtodo to start | `todo.py add-subtodo --summary=...` (on the parent) | `start_subtodo` (+ child branch & `BaseSha`) |
| a subtodo to land | git-merge the child, then `todo.py merge-subtodo <child-id>` | `merge_subtodo` (+ merge sha) |
| local coding | make the change, then `todo.py work-item-done` (dirty tree commits it, message = `-m` or the item summary; clean tree records HEAD) | `code` (+ HEAD sha) |
| too coarse | `todo.py work-item-insert --summary=...` to split it, then re-poll | new task at the cursor |
| blocked on children | `todo.py wait-for <id>...` / `wait-and-merge <id>...`, or `set-state userneeded --note=...` and **come back and poll later** | -- |
| empty (`is_done == true`) | run `todo.py doctor` (must be `ok`); read the done items (`todo.py jq self '.WorkItems'`) and **synthesize a 1-3 sentence ActualSummary of what actually landed**; then `todo.py set-state done --actual-summary="..."` | `done` (State) |

"Come back and ask again later" is a first-class outcome: when the next item is
a barrier, wait/poll rather than forcing progress.

**Finish (the `is_done == true` branch of the loop).** When `is-done`, the last
item is a `code` or `merge` commit (invariant #6), so `todo.py last-sha` is the
branch's last commit. This is a directed sequence, not an optional coda:

1. Run `todo.py doctor`; it must be `ok` before finishing.
2. Read the completed WorkItems -- `todo.py jq self '.WorkItems'` -- and
   **synthesize a 1-3 sentence ActualSummary of what actually landed**: how the
   work panned out versus the planned `Summary`, noting any pivots, descoped
   items, or surprises. This is the retrospective, not a restatement of the plan.
3. `todo.py set-state done --actual-summary="<that synthesis>"`.

The `--actual-summary` is not optional here: it is the merge message the
parent's `merge-subtodo` reuses (falling back to `Summary.raw` only when a child
skipped this step). A parent only finishes after every subtodo shows `merged`
(see Recursive completion).

Each todo -- parent or child -- runs this same loop on its own branch. Split
into child todos when the Body is too big for one clean run **or** when
independent research domains would overload a single context (see
Context-scoped subtodos); keep sequential small steps as parent WorkItems.

We are iteratively moving process weight into the tool. `work-item-read` now
emits a `next` hint that classifies the mechanical next command directly (the
finish sequence, or the primitive named by a WorkItem's `execution` block,
defaulting a plain task to `work-item-done`). The tool emits only mechanism as
structured data; policy -- when to split a task or spin off a subtodo -- stays
in this skill's dispatch table, so the two do not drift.

## Minimal skeleton

```json
{
  "Id": "8f3a2c1d9e7b4f6a5c0d8e2b1f4a6c3d7e9b0f2a4c6d8e0f1a2b3c4d5e6f7a8b",
  "Branch": "8f3a2c1d-fix-pico2w-env-sensor",
  "create_dt": "2026-06-22T16:00:00Z",
  "update_dt": "2026-06-22T16:00:00Z",
  "State": { "init": {} },
  "Scope": {
    "path_to_project": "/Users/johan/github.com/jovlinger/example",
    "path_from_root": "firmware/pico2w"
  },
  "Summary": { "raw": "Fix pico2w environment sensor" },
  "Body": { "raw": "Sensor reads stale after sleep. Reproduce, fix driver init, add test." },
  "AC": "AHT20 returns fresh readings after 10 sleep/wake cycles; test in CI."
}
```

## Related

- `frequentcommits` -- policy for splitting work into WorkItems and committing;
  this skill (and `todo.py`) is the mechanism it tracks against.
- `bookmark-management` -- handoff note when pausing mid-ticket with partial state.
- `project-lifecycle` -- separate markdown `TODOs.md` lifecycle; coexists, do
  not merge formats without user direction.

## Deferred (post-v1)

Intentionally not designed yet; do not implement on a normal run.

- **Stack across branches** -- push/peek/pop over many tickets ordered by
  `create_dt` within a matching `Scope`. Needs a registry or cross-branch
  discovery; on one branch the "stack" is just the lone file.
- **Dependency graph** -- `waiting { waiting:[], waited:[] }` on a blocked
  ticket and a `waiter` Id on its parent's `working`, unblocking when `waited`
  reach `done`. Must stay acyclic; `doctor` audits this.
- **Embeddings** -- canonical embedding source names and the chunked-vector
  format for `Summary`/`Body` similarity recall.
- **`working` lock semantics** -- honoring `expire` and asking before taking
  over an expired ticket owned by someone else (single-owner branches make this
  rare).

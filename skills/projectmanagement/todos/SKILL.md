---
name: todos
description: >-
  Branch-bound TODO.json task tickets managed through the todo.py CLI (one
  ticket per git branch). TRIGGER, necessary and sufficient: the user says
  "TODO", "todo", "ticket", "branch task", or asks to track/manage task state --
  invoke immediately on any of these. On invoke, route ALL TODO.json access
  through todo.py; never read or write TODO.json directly. The full workflow,
  CLI, and schema live in this skill body and load only when triggered.
disable-model-invocation: false
---

# TODO.json

status: living document

Associative memory for pruned contexts: a task ticket that lives with a git
branch. One branch carries **zero or one** `TODO.json`.

## Definitions

- **`gitroot`:** `git rev-parse --show-toplevel` -- the local clone directory.
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
5. Parent: `wait-for` / `wait-and-merge`, then one synthesis WorkItem using merged
   branches, then parent `done`.

Do **not** file subtodos when the work is a short linear edit, a single subsystem,
or when child branches would be empty shells with no distinct artifact -- use
parent WorkItems instead.

**v1 mainline (what a normal run uses):** find the repo root, create one ticket
if none exists, work it `init -> working -> done`, read and patch fields with
`todo.py`. Use subtodos when the ticket spans multiple independent research
domains (above). Stacks across branches, dependency graphs, and embeddings beyond
that are **deferred** and listed at the bottom.

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
| `todo.py read <selector>` | implemented | Locate the branch (or worktree) whose `TODO.json` matches `<selector>` and print the ticket JSON. Id selectors are any **4+ hex unambiguous prefix**, or the full digest. `curr`/`self` resolve to the checked-out branch's todo, even when the branch name does not contain the Id. Resolution is **catalog-first** (`~/.todo/catalog.txt`): a fast, cross-repo lookup that skips scanning every git ref; it falls back to a current-repo ref scan only when the catalog has no hit. Local-first: remote fetch is feature-flagged off (`FETCH_ENABLED`) |
| `todo.py list` | implemented | Print the append-only catalog (`~/.todo/catalog.txt`): one row per todo as `repo  id  branch  summary` -- where todos live, written on `init`. Where-to-find-it only; use `read <id>` for content. `$TODO_CATALOG_PATH` overrides the path |
| `todo.py read-path <selector> <path>` | implemented | Low-level path read. Reads one value from a selected todo. `<path>` is the internal dot-path syntax, e.g. `Body.raw` or `WorkItems.0.summary`. |
| `todo.py set-path <selector> <path> <value\|->` | implemented | Low-level path write. Sets one value on a selected todo, with `-` reading the value from stdin. This is the canonical write primitive; higher-level commands are syntax sugar plus path-trigger behavior. |
| `todo.py jq <selector> <jq-filter>` | implemented | Read-only jq-compatible projection. Shells out to `jq` internally unless/until a 100% compatible Python jq library is chosen. This keeps callers behind `todo.py` while preserving jq filter semantics. |
| `todo.py init --summary=...` | implemented | Mint Id (or `--id`), create local branch, write `TODO.json`, commit, and append a row to `~/.todo/catalog.txt` (`$TODO_CATALOG_PATH` to override). Refuses when current branch already has a ticket. `--agent-type` / `--session-id` (or `$TODO_AGENT_TYPE` / `$TODO_SESSION_ID`) record the creating agent in the ticket's `Agent` field |
| `todo.py add-subtodo --from-json=...` | implemented | From a parent todo branch: create child branch + `TODO.json`, commit, return to parent, register in `Subtodos` (`add-child` alias) |
| `todo.py set-state <state>` | implemented | Sugar for setting `State` to a single-key object, equivalent to `set-path self State '{"<state>": {...}}'` plus path triggers. Valid states are `init`, `working`, `done`, `merged`, `userneeded`, `stopped`; commit by default |
| `todo.py merge-subtodo <id>` | implemented | After child is `done`: checkout child branch, set `merged`, commit; update parent `Subtodos[].State` to `merged` (`merge-child` alias) |
| `todo.py set --summary=... --body=... --ac=...` | implemented | Sugar for `set-path self Summary.raw ...`, `set-path self Body.raw ...`, and `set-path self AC ...` |
| `todo.py work-item-add --summary=...` | implemented | Sugar for appending `{summary, done:false}` to `WorkItems` (`chunk-add` alias). Keep richer operations demand-driven. |
| `todo.py work-item-done [--index=N]` | implemented | Sugar for setting `WorkItems.<index>.done` to `true`; default index is first open (`chunk-done` alias) |
| `todo.py update <id> <jsonpath> <value\|->` | implemented | Compatibility alias for `set-path`. |
| `todo.py wait-for <id>...` | implemented | Poll selected child todos until they reach a target state, default `done`, without direct file reads. Initial implementation polls through todo selectors; better signaling can follow real usage. |
| `todo.py wait-and-merge <subtodo-id>...` | implemented | Poll child todos until `done`, then run merge bookkeeping for each child. |
| `todo.py doctor [<selector>]` | implemented | Validate schema, selector resolution, state shape, subtodo references, dependency cycles, and impossible waits. |
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
| `read-path <selector> <path>` | Print one internal dot-path value. |
| `set-path <selector> <path> <value|->` | Set one internal dot-path value. |
| `jq <selector> <filter>` | Run a jq filter against the selected todo and print the result. |

Higher-level commands are special syntax for these primitives, plus triggers.
Triggers fire by changed path, not by command name, so `set-state done` and
`set-path self State '{"done": {}}'` share the same downstream behavior.

## Placement and branch rule

| Rule | Value |
|------|-------|
| Path | `<repo-root>/TODO.json` only |
| Per branch | 0 or 1 file (never 2+) |
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
"lives." Find todos by repo + branch (and the `~/.todo/catalog.txt` registry);
use `git worktree list` only to locate a branch's current checkout when one exists.

A todo's working tree may live in a dedicated git worktree rather than the main
checkout. **Existing worktrees are found with `git worktree list` and are never
moved.** Only *new* worktrees follow the placement convention below; the path is
never passed on the command line -- it is a creation convention, not a lookup
key.

New worktrees go under a default root (`~/.todo/worktrees/`, override with
`$TODO_WORKTREES_DIR`), nested by the repo's full path with the branch as the
leaf:

```
~/.todo/worktrees/<repo-path>/<branch>
# e.g. ~/.todo/worktrees/github.com/jovlinger/util/my-branch
#      ~/.todo/worktrees/github.com/jovlinger/configfiles/todo-webui
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
todo.py read <known-id-prefix>        # load a known ticket; do not read TODO.json directly
todo.py read self                     # current-branch lookup
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
  or `todo.py update <id> <jsonpath> <value|->`.
- Temporary seed JSON files passed to `--from-json` or `--work-items-file` are
  inputs to the CLI, not direct `TODO.json` access. They may be authored as
  ordinary files, then consumed by `todo.py`.

```bash
# read the full ticket JSON
todo.py read 8f3a2c1d

# read one field
todo.py read-path self Summary.raw

# jq-compatible read projection (todo.py shells out to jq internally)
todo.py jq self '.Id, (.State | keys[0]), .Summary.raw'

# patch simple fields on the current branch
todo.py set --ac="new criteria"

# patch a field on any todo by id; use "-" to read the new value from stdin
printf '%s\n' "new body" | todo.py update 8f3a2c1d Body.raw -

# canonical spelling for the same low-level write
printf '%s\n' "new body" | todo.py set-path 8f3a2c1d Body.raw -

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

`Summary.raw` and `Body.raw` are always present; embedding keys are optional
enrichments, omitted on first write and backfilled later if ever.

### WorkItems and coordination

`WorkItems` is the ordered work plan for a todo. Simple items only need
`summary` and `done`. Larger work may add an `execution` object to make ordering
and parallelism explicit without inventing a scheduler.

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
2. Child finishes with `todo.py set-state done --last-commit=...`.
3. Parent `todo.py wait-for <child>...` polls `todo.py read-path <child> State`
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

### Richer work-item operations

Current operations cover the common story: append a simple WorkItem and mark the
next or indexed item done. Add more commands only when a concrete use case
appears. Examples that would justify a command:

- Reordering a long plan after the user changes priorities.
- Marking a blocked item with a note rather than completing it.
- Updating `execution` metadata after subtodos are split differently than first
  planned.

Until those cases recur, use `set-path` for precise edits, or
`set --work-items-file` when replacing the whole plan is clearer.

### Worktree operations

Manual worktrees are enough until a workflow requires automation. A future
`worktree add/list/remove` family is justified when the agent needs to run parent
and child todos concurrently in separate checkouts, or when a parent needs to
enumerate child worktrees without relying on chat memory. If there is no concrete
parallel-checkout use case, keep worktree creation/listing manual.

## Doctor checks

`todo.py doctor [<selector>]` starts as a read-only audit. First checks:

- Selector resolution: ids are unambiguous; `self`/`curr` resolves to exactly one
  branch-bound todo.
- Schema: allowed top-level fields only; required fields present; optional fields
  are either valid values or `null`.
- State: `State` has exactly one key and the state name is valid.
- References: `Parent` and `Subtodos` point to existing todos when discoverable.
- Dependency graph: waiting/barrier relationships are acyclic.
- Wait sanity: a parent is not waiting on itself, a missing child, or a child in
  an impossible terminal state.

## How to work a ticket

1. **Load:** `todo.py read <id-prefix>` or `todo.py read self`. Never assume chat memory matches the file.
2. **Create parent:** `todo.py init --summary=... --body=... --ac=...` (mints Id, creates branch, writes and commits `TODO.json`). Do **not** hand-edit `TODO.json` for routine updates.
3. **Create child (when warranted):** on the parent branch, `todo.py add-subtodo --from-json=<seed.json>` or `add-subtodo --summary=...`. Registers the child under parent `Subtodos`. Use for context-scoped fact-finding (DMZ CLI, per-hardware upgrade paths, etc.) -- not for every WorkItem.
4. **Work loop:** `todo.py set-state working` -> work items (`work-item-add` / `work-item-done`) on the owning branch -> `todo.py set-state done --last-commit=...`. Children run the same loop on their branch; parent may delegate to local subagents one child at a time or in parallel.
5. **Parent merge:** after merging the git branch, `todo.py merge-subtodo <child-id-prefix>` on the parent branch sets child `State` to `merged` and updates parent `Subtodos[].State`.
6. **Field edits:** `todo.py set --ac=... --body=... --summary=...` on the current branch, or `todo.py update <id> <jsonpath> <value|->` on any todo by id. Long term spelling is `set-path <selector> <path> <value|->`.

Split into child todos when the Body is too big for one clean run **or** when
independent research domains would overload a single context (see
Context-scoped subtodos). Keep sequential small steps as parent WorkItems only.

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

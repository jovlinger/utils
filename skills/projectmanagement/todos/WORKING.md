# Working a todo

status: living document - **normative owner** for lifecycle, worktrees, subtodo
integration, finish/teardown, handoff, and chat reporting

CLI syntax and schema -> [`IMPLEMENTATION.md`](IMPLEMENTATION.md)
Ticket design / decomposition -> [`GROOMING.md`](GROOMING.md)
Intent router -> [`SKILL.md`](SKILL.md)

There is exactly one normative sequence per operation below. Other docs link
here; they do not restate these steps.

---

## Operator intents

1. [Start or resume](#1-start-or-resume)
2. [Poll and execute one WorkItem](#2-poll-and-execute-one-workitem)
3. [Split or delegate](#3-split-or-delegate)
4. [Wait and integrate child work](#4-wait-and-integrate-child-work)
5. [Handle `userneeded` or `stopped`](#5-handle-userneeded-or-stopped)
6. [Finish and remove the worktree](#6-finish-and-remove-the-worktree)
7. [Handoff to parent or PR](#7-handoff-to-parent-or-pr)
8. [Report the result](#8-report-the-result)

---

## Hard rules (operational)

1. **CLI-only ticket access** -- every read/write through `todo.py` (see
   [`IMPLEMENTATION.md`](IMPLEMENTATION.md#cli-implemented-commands)).
2. **Explicit selector** -- no current-branch alias; capture and reuse `Id`.
3. **Tool-owned storage** -- `todo.py` owns the ticket record and backend
   selection. Never treat `TODO.json` as the live record. Backend placement is
   normally irrelevant to working a ticket; see
   [`IMPLEMENTATION.md`](IMPLEMENTATION.md#repository-local-storage).
4. **Dedicated worktree for code** -- never `git checkout` the todo branch in
   the main checkout while working it.
5. **No parent `done` before tracked children are `merged`** on the parent
   record (INFO backlinks excluded).
6. **Sequential by default** -- when working a todo with subtodos, work children
   one at a time in stack order unless the user explicitly asks for parallel
   work or the children are genuinely independent context-heavy research (see
   [`GROOMING.md`](GROOMING.md#workitem-vs-subtodo)). Parallel is an exception,
   not the default.

### Context shedding between sequential subtodos

The durable state is the **todo record + git**, not the chat. After finishing
and merging one subtodo, shed finished-child context with whatever mechanism
your host agent provides (compact/summarize/new session/etc.), then reload the
next frame with `todo.py prompt <id>` / `todo.py read`. Do not require a
vendor-specific slash command. Committed work and store writes are never
rewound.

---

## Default branch (`DEFAULT_BRANCH`)

The main checkout must stay on the repository's **configured default branch**
while any todo is worked in a linked worktree. That branch may be `master`,
`main`, `dev`, or another name -- never hard-code `master` in checks.

Resolve once per session:

```bash
MAIN=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')

DEFAULT_BRANCH=$(git -C "$MAIN" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
if [ -z "$DEFAULT_BRANCH" ]; then
  for cand in master main dev; do
    if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$cand"; then
      DEFAULT_BRANCH=$cand
      break
    fi
  done
fi
if [ -z "$DEFAULT_BRANCH" ]; then
  echo "cannot determine DEFAULT_BRANCH; set origin/HEAD or create master/main/dev" >&2
  exit 1
fi
```

Every "main checkout branch" check compares against `$DEFAULT_BRANCH`.

### Why the main checkout stays on the default branch

Checking out a todo branch in the main tree couples any local storage churn
into feature-branch history. Keep code work in linked worktrees only.

---

## Worktree setup

`todo.py ensure_worktree <id> [--init]` runs `git worktree add` at the conventional
path when the todo branch exists. Pass `--init` to promote a groom todo first
(same as `init --id <id> --stay-on-parent` when the branch is missing; noop when
it already exists). Without `--init`, run `init` manually first.

**On entry** (before `set <id> --state working`, `work-item-done`, or code edits):

```bash
# 1) Main checkout on DEFAULT_BRANCH
git -C "$MAIN" branch --show-current   # must equal $DEFAULT_BRANCH

# 2) Init branch (if groom) and create/reuse worktree
todo ensure_worktree <id> --init
cd "$(todo ensure_worktree <id> | jq -r .worktree)"

# 3) Verify CWD is the linked worktree of the todo branch
test "$(git rev-parse --show-toplevel)" != "$MAIN"
test "$(git branch --show-current)" = "$BRANCH"
```

Prefer `todo.py init --stay-on-parent` when filing from the main checkout, then
add the worktree.

**INVARIANT:** every FINAL state (`done`, `merged`, `rejected`) implies **no
live worktree** for that todo. Teardown is mandatory on finish (below), not
optional cleanup. `set --state ...` is store-only and does **not** remove
worktrees.

---

## Recursive completion (subtodos)

Parent goal: finish local work **and** merge tracked subtodos. Setting a child
`done` without `merge-subtodo` on the parent is an incomplete call.

| Rule | Meaning |
|------|---------|
| Every subtodo must terminate | Child reaches `done`/`merged`, or surfaces via `userneeded`/`stopped` |
| No silent skips | Do not mark parent `done` while any tracked subtodo is still `ready`/`working`, or `done` but not yet bookkept as `merged` on the parent |
| Git integrate, then bookkeeping | After the child's branch is merged/absorbed into the parent branch, run `merge-subtodo` (or `wait-and-merge` after the git merges) |
| Parent synthesis last | Parent `done` only after all tracked subtodos are `merged` (or user-waived) |

Anti-patterns: landing all code on the parent while children stay `ready`;
marking children `done` without working their branches; parent `done` while
`todo.py read <parent> | jq -r '.Subtodos[].State'` still shows `ready` or
`done` (unmerged). INFO rows are excluded from merge-completeness.

---

## 1. Start or resume

```bash
todo.py prompt <id>          # WHY -> WHAT (Parent chain); first action for a worker
todo.py read <id>            # full record
# verify DEFAULT_BRANCH + worktree (Worktree setup)
todo.py set <id> --state working --owner=<agent>
```

Startup context: `Parent` is a list of `{Id, Branch}` refs. `add-subtodo` sets
element 0 (structural) and registers a tracked subtodo. `set --parent` writes
follow-only INFO backlinks -- see
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#subtodos-and-waiting). For mergeable
children always use `add-subtodo`.

If promoting a groomed ticket first: `todo.py init --id <id> --stay-on-parent`,
then worktree setup. Creation policy lives in
[`GROOMING.md`](GROOMING.md#two-phase-make-vs-work).

---

## 2. Poll and execute one WorkItem

The tool carries process weight -- poll for the next step:

```bash
todo.py work-item-read <id>   # cursor + mechanism `next` hint
todo.py is-done <id>          # exit 0 when nothing left
```

`next` is mechanism, not policy. Override when the dispatch table says split or
spawn a subtodo.

| Cursor item is... | Do | Tool records |
|-----------------|----|--------------|
| a subtodo to start | `todo.py add-subtodo <parent-id> --summary=...` | `start_subtodo` |
| a subtodo to land | **git-merge** child into parent branch, then `todo.py merge-subtodo <child-id>` | `merge_subtodo` |
| local coding | edit in todo worktree, then `todo.py work-item-done <id>` | `code` |
| no-code step | `todo.py work-item-done <id> --checkpoint -m "..."` | `checkpoint` |
| too coarse | `todo.py work-item-insert <id> --summary=...` | new task at cursor |
| impossible as written | `todo.py work-item-done <id> --blocked -m "<long form>"`, then the `userneeded` note ([5](#5-handle-userneeded-or-stopped)) | `code` with the no-change sentinel |
| blocked on children | integrate/wait (below), or `userneeded` and return later | -- |
| empty (`is-done`) | [Finish](#6-finish-and-remove-the-worktree) | `done` |

Full command flags -> [`IMPLEMENTATION.md`](IMPLEMENTATION.md#work-items).

---

## 3. Split or delegate

- Short linear steps -> parent WorkItems (`work-item-add` / `work-item-insert`).
- Independent context-heavy domains -> subtodos (`add-subtodo`), still
  **sequential by default** unless parallel is authorized (grooming policy).
- Capability tiers on each unit -> [`GROOMING.md`](GROOMING.md#capability-tiers).

---

## 4. Wait and integrate child work

**`wait-and-merge` and `merge-subtodo` do not merge git branches.** They only
poll (for wait-and-merge) and update store bookkeeping. The recorded
`merge_subtodo` sha is the **parent branch tip after your git integration**.

Normative sequence per child (or batch):

1. Child lifecycle to `is-done`, then `todo.py set <child-id> --state done
   --actual-summary="..."` (and child worktree teardown per section 6).
2. In the **parent** worktree, on the parent branch: integrate the child
   (`git merge <child-branch>`, or cherry-pick / equivalent absorption you can
   verify). Resolve conflicts; confirm the parent tip contains the child's work.
3. Bookkeeping: `todo.py merge-subtodo <child-id>`
   or, after all intended git merges: `todo.py wait-and-merge <child-id>...`
   (still bookkeeping-only; fails usefully if the parent branch tip is missing).
4. Confirm parent `Subtodos[].State` is `merged` for each tracked child.

Optional barrier WorkItems may name `execution.primitive: "wait-and-merge"` so
`work-item-read`'s `next` hint points at the command -- policy still requires
the git step first.

Portable coordination: poll with `wait-for` / `wait-and-merge`. Same-session
harness completion notifications (when available) are a convenience only.

---

## 5. Handle `userneeded` or `stopped`

```bash
todo.py set <child-id> --state userneeded --note="..."
todo.py set <parent-id> --state userneeded --note="blocked on child <id>: ..."
```

Never leave a child in `ready`/`working` indefinitely without escalating.
`stopped` is a user override halt (`--note`).

### Recording a blocked item

A work item that cannot be completed as written -- the approach turns out to
require solving P==NP, the data it needs does not exist, the API it assumed is
not there -- is **not** silently left at the cursor and **not** disposed of in
chat. Record it in TWO places, long form and short form:

| Where | What | Why there |
|-------|------|-----------|
| **The work item** (`work-item-done --blocked -m "..."`) | The LONG form: what was tried, what was actually found (concrete: fixture names, ids, counts, error types), why the approach cannot work, and the options as you see them | The WorkItems trail is what a future agent walks. This is the same durable slot a commit message occupies for work that succeeded -- hence `-m` is mandatory here, unlike on a checkpoint |
| **The state** (`set <id> --state userneeded --note="..."`) | The SHORT form: one or two lines naming the item and the decision being asked for, pointing at the work item | The note is read ONCE, by the user deciding what to do next. A blocker narrative pasted in full there buries the actual question |

```bash
todo.py work-item-done <id> --blocked -m "Not achievable with the committed corpus.
MIXED-22: the 18 checklist ids in the burst match none of the 2 recorded...
STORM-30: no interchange fixture exists at all...
Options: (a) descope to checklist_doc_attach.json, (b) wait for a healthy tenant, (c) move to layer 3."
todo.py set <id> --state userneeded --note="http://localhost:8765/<id>/objid/<objid> blocked: replay corpus lacks the recordings. Three options on the work item, need a pick."
```

Both writes, not one. The state note without the item leaves the trail claiming
the step is merely unstarted; the item without the state note leaves a stuck todo
that never asks the user anything. The **permalink to the blocked item** is what
you paste into chat, a PR, or another todo -- not a retelling.

`--blocked` requires a clean tree (commit or discard the partial attempt first),
refuses `--sha`, and refuses to be combined with `--checkpoint`. Reach for
`--checkpoint` when the step genuinely finished without producing code; reach for
`--blocked` when it did not finish at all. Because the sentinel cannot be the
last item of a done todo (invariant #6), a blocked tail keeps the todo honestly
unfinished -- see
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#workitems-and-invariants).

---

## 6. Finish and remove the worktree

When `todo.py is-done <id>` is true, run this **directed** sequence. State
transition and worktree removal are separate halves; both must succeed.

1. **In the todo worktree**, verify:
   - working tree clean (`git status`)
   - `todo.py is-done <id>` (exit 0)
   - `todo.py doctor <id>` -> ok (no hard findings)
   - `todo.py last-sha <id>` matches the intended branch tip (invariant #6)
2. Read completed WorkItems (`todo.py read <id> | jq '.WorkItems'`) and
   **synthesize** a 1-3 sentence `ActualSummary` (retrospective vs planned
   Summary -- pivots, descopes, surprises).
3. **Save the worktree path** and leave it (`cd` to main checkout or elsewhere):
   `WT=$(git rev-parse --show-toplevel)`.
4. **Set terminal state** (store-only):
   `todo.py set <id> --state done --actual-summary="<synthesis>"`
   (use `--state merged` / `--state rejected` only for those dispositions; same
   teardown obligation applies).
5. **Remove that exact worktree** and verify:
   ```bash
   git worktree remove "$WT"
   git worktree list   # must not list $WT
   ```
6. Branch handoff/retirement is **separate** -- see section 7. Do not `git branch -D`
   as part of finish.

**Failure handling**

| Failure | Action |
|---------|--------|
| Dirty tree / not `is-done` / doctor fails | Do not set FINAL state; fix or surface `userneeded` |
| `set --state done` fails after leaving WT | Re-run `set` from any cwd in the repo; do not remove WT until state is FINAL |
| State is FINAL but `worktree remove` fails | Resolve (busy WT, dirty) then remove; orphan FINAL+live-WT is an invariant violation -- next agent/`doctor` sweep should remove it |
| Remove succeeded but you still need the branch | Fine -- branch and commits remain until handoff delete gate |

Parent finishes only after every tracked subtodo shows `merged` (or explicit
user waiver).

---

## 7. Handoff to parent or PR

### Subtodo -> parent

Git-integrate into the parent branch, then `merge-subtodo` (section 4). Teardown of
the child worktree happens at child FINAL (section 6).

### Root todo -> PR

```bash
todo.py set <id> --state merged --pr <N>    # "Push PR" transition after done
```

`doctor` fills `merge_commit` / moves closed-unmerged to `rejected`. See
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#state-machine).

### Branch retirement (destructive -- gated)

Worktree teardown is reversible (checkout only). **Deleting a branch** is
separate and requires **all** of:

1. Ticket records handoff evidence (`merged` with `merged_into` and/or `pr`, or
   documented cherry-pick / absorption note on the ticket).
2. No live worktree for that branch.
3. Durable ref pushed where the workflow expects remote backup (when the repo
   uses a remote).
4. **Explicit user authorization** before `git branch -D`.

Remote branch deletion is out of scope unless the user separately requests it.
Do not treat "equivalent-content absorption" as a silent delete license without
ticket evidence + user auth.

---

## 8. Report the result

Namespace ids: `todo:d56d`, `sha:ce66a4`, `pr:22660`, `branch:dev`.

**Name a work item by PATH, not by index notation:** `todo:d56d/workitem/18`,
and deeper when you need a field: `todo:d56d/workitem/18/summary`. This is the
same grammar the permalink syntax uses, so the token a reader sees in chat is the
token that resolves. The older organic `WI[18]` / `todo:x.WI[4]` forms stay
readable but are not written any more. Prefer the `objid` form
(`todo:d56d/objid/0a3f`) when naming a durable object, since an index shifts --
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#permalinks).

**While working:** one short action line per action; no preamble.

**Durable notes** belong in the commit message (`work-item-done -m`), not chat.

**Verdict grades the MAIN todo**, not the last step:

| verdict | when |
|---------|------|
| `success` | FINAL success: `done` or `merged` |
| `mix` | progress, unfinished; or `userneeded` / `stopped` |
| `fail` | stuck -- cannot complete a work item as written |

`fail` is the more specific case and wins the overlap: `userneeded` awaiting a
decision is `mix`, but `userneeded` because an item is IMPOSSIBLE as written is
`fail` -- and that item should already be recorded with `--blocked` (section 5).

Always report `N of M work items done, cursor at todo:<id>/workitem/<i>`.
Untracked mid-run asks become WorkItems (`work-item-add`), not prose side
conditions.

SUMMARY shape: `SUMMARY: <success|fail|mix> [clause]` -> effect of the todo as a
whole -> short bullets for interesting items only. Never report "spawned a
subtodo" as a result; mention children only when their **outcome** matters.

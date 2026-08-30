---
name: todos
description: >-
  Branch-bound todo task tickets managed through the todo.py CLI (one ticket
  per git branch). TRIGGER: the user says "TODO", "todo", "ticket", "branch
  task", "HICAP", "MIDCAP", "LOCAP", "groom", or asks to track/manage task
  state -- invoke immediately. Route ALL ticket access through todo.py; never
  read or write TODO.json or a backend by hand. Load detailed references on
  demand via the intent router below -- do not preload the full CLI/schema/runbook
  unless needed.
disable-model-invocation: false
---

# Todo tickets

status: living document - entry skill (router)

**Cursor agents:** before working a ticket, read [`CURSOR.md`](CURSOR.md) (tier
dispatch, do not stop mid-loop, worktree rules restated for Cursor).

Associative memory for pruned contexts: a task ticket bound to a git branch.
One branch carries **zero or one** ticket, addressed through `todo.py` by
explicit `Id` (no current-branch selector). Storage backend selection is a
tool feature; agents do not need to know it. Legacy `TODO.json` is import-only.

## Roles and capability tiers (read first)

| Role | Who | Job |
|------|-----|-----|
| Groomer | HICAP (sparingly) | Mint, decompose, write AC/Body/LongSummary, tag tiers, decide WorkItem vs subtodo -- do **not** implement or `init` unless asked to work |
| Worker | MIDCAP / LOCAP | Execute one WorkItem at a time on the todo branch in a dedicated worktree |
| Orchestrator | Parent context | Bookkeeping, child launch, synthesis after merge |

| Tier | Meaning | Claude examples (keep) |
|------|---------|------------------------|
| HICAP | Flagship reasoning; spend sparingly | Opus-class (e.g. Opus 5, Fable 5) |
| MIDCAP | Default workhorse | Sonnet-class (e.g. Sonnet 5) |
| LOCAP | Small/fast/cheap | Haiku-class (e.g. Haiku 4.5) |

Tag WorkItems / subtodos `[HICAP]` / `[MIDCAP]` / `[LOCAP]`. Full tier rules and
the Cursor model map: [`GROOMING.md`](GROOMING.md#capability-tiers).

## Intent router

Load **only** what the user intent needs:

| Intent | Open |
|--------|------|
| **Cursor: work / proceed / continue a ticket** | [`CURSOR.md`](CURSOR.md) **first**, then [`WORKING.md`](WORKING.md) |
| make / groom / plan / decompose / size / tier / HICAP / MIDCAP / LOCAP | [`GROOMING.md`](GROOMING.md) |
| start / resume / work / wait / finish / handoff / report | [`WORKING.md`](WORKING.md) |
| command syntax / schema / storage / migrate / doctor / permalinks / compatibility | [`IMPLEMENTATION.md`](IMPLEMENTATION.md) |

## Everyday quick reference

```bash
TODO=skills/projectmanagement/todos/todo.py

# make / groom (store-only; no branch, no init yet)
ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."
"$TODO" work-item-add "$ID" --summary="[MIDCAP] ..."
# stay in State groom until the user asks to work

# promote when ready to work (branch only; worktree is separate)
"$TODO" init --id "$ID" --stay-on-parent

# one-shot: init branch if needed, then linked worktree (preferred at work start)
"$TODO" ensure_worktree "$ID" --init
cd "$("$TODO" ensure_worktree "$ID" | jq -r .worktree)"

# work loop (inside the todo worktree -- see WORKING.md)
"$TODO" prompt "$ID"
"$TODO" set "$ID" --state working
"$TODO" work-item-read "$ID"          # poll; follow WORKING.md dispatch
"$TODO" work-item-done "$ID" -m "..." # or add-subtodo / merge after git merge

# finish (WORKING.md section 6 -- includes worktree remove after set done)
"$TODO" doctor "$ID"                  # must be ok
"$TODO" set "$ID" --state done --actual-summary="..."
```

Authoritative finish, child integration, and worktree teardown:
[`WORKING.md`](WORKING.md). Full command table:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#cli-implemented-commands).

## Domain model (compact)

- **`gitroot`:** current working tree (`git rev-parse --show-toplevel`) -- git ops.
- **`main checkout root`:** primary worktree (first `git worktree list` entry);
  keep it on the repository's default branch while code is worked elsewhere.
- **Todo branch / worktree:** code lives on the ticket's `Branch`, checked out
  only in a dedicated linked worktree -- never in the main checkout while working.
- **Tracked subtodo:** child from `add-subtodo` (must be git-integrated then
  `merge-subtodo`'d). **INFO backlink:** follow-only parent link from `set --parent`.
- **Repo selection:** CWD's gitroot; no `--repo` flag -- `cd` into the repo first.

## Safety rules (non-negotiable)

1. **CLI-only** -- all ticket reads/writes via `todo.py` (never direct store /
   `TODO.json` access). Piping `todo.py read` to `jq` is fine.
2. **Explicit selector** -- capture Id from `mint`/`init`; use 4+ hex prefix or full digest.
3. **Tool-owned storage** -- `todo.py` owns live records and backend selection;
   never infer ticket state from a branch-local file.
4. **Dedicated worktree for code** -- main checkout stays on the repo's
   `DEFAULT_BRANCH`; see [`WORKING.md`](WORKING.md#default-branch-default_branch).
5. **No parent completion before tracked children are integrated** -- git-merge
   (or verified absorption) **then** merge bookkeeping; parent `done` only after
   tracked subtodos are `merged` (or user-waived).
6. **Sequential default** -- work subtodos one at a time unless the user asks for
   parallel or grooming authorizes independent research fan-out
   ([`GROOMING.md`](GROOMING.md#workitem-vs-subtodo)).

Related: `frequentcommits` (WorkItem sizing policy); `bookmark-management`;
`project-lifecycle` (separate `TODOs.md` -- do not merge formats without user direction).

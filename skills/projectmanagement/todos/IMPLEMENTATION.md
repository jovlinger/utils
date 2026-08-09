# Todo implementation reference

status: living document · normative owner for CLI, storage, schema, migrations,
permalinks, doctor, compatibility, and planned features

Load this when you need exact command syntax, record fields, store layout, or
compatibility notes. Policy and runbooks live elsewhere:

- Intent / safety card → [`SKILL.md`](SKILL.md)
- Ticket design / dispatch → [`GROOMING.md`](GROOMING.md)
- Start → finish runbook → [`WORKING.md`](WORKING.md)

---

## Terminology (frozen)

| Term | Meaning |
|------|---------|
| **ticket** / **todo** | One task record addressed by `Id` |
| **record** | The JSON object for a ticket (sqlite or json-dir backend) |
| **resolved store** | The todo directory chosen for this invocation (`todo.py basedir`) |
| **todo branch** | Git branch named in the record’s `Branch` field |
| **todo worktree** | Dedicated linked worktree checking out that branch |
| **tracked subtodo** | Child registered via `add-subtodo` (merge obligation) |
| **INFO backlink** | Follow-only `Subtodos` row (`State: "INFO"`) from `set --parent`; no merge obligation |

Do **not** teach agents that a live ticket “lives in” `TODO.json`. Current
records live in the resolved store. Legacy `TODO.json` is import-only — see
[Compatibility](#compatibility-history).

---

## Document sections

1. [Current public contract](#current-public-contract) — agents may rely on this
2. [Maintainer internals](#maintainer-internals)
3. [Compatibility / history](#compatibility-history)
4. [Deferred / planned](#deferred-planned) — non-normative

---

# Current public contract

## Store resolution

Resolved once per `todo.py` invocation. The storage anchor is the repo’s
**main checkout root** (first `git worktree list` entry), not the current
linked worktree — every worktree of a repo shares one store.

1. `$TODO_DIR` when set and it holds a store (`config.json`, `sqlite.db`, or `storage/`)
2. `<main-checkout-root>/.todo/` when that holds a store
3. `$HOME/.todo/` when that holds a store

If none exist, create under the first applicable default: `$TODO_DIR`, else
`<main-checkout-root>/.todo/`, else `$HOME/.todo/`.

| Item | Location |
|------|----------|
| Tickets | `<todo-dir>/sqlite.db` or `<todo-dir>/storage/*.json` |
| Worktrees (convention) | `<todo-dir>/worktrees/<repo-path>/<branch>` |
| Embeddings | In ticket JSON; sqlite also mirrors a derived index |

`TODO_USE_JSON=1` enables legacy file mode (import-oriented). There is **no
`--repo` flag** — `cd` into the target repo/worktree; CWD must be a git repo.

Print the resolved base with `todo.py basedir`. Print a todo’s main-checkout
repo path with `todo.py repodir <selector>`.

## Selectors

| Selector | Meaning |
|----------|---------|
| `<id-prefix>` | Unambiguous 4+ hex prefix of the 64-hex `Id`, or the full digest |
| `ALL` | Whole corpus — recognized by `doctor`, `log`, `export-to-file`, `tag-clear` |

Former `self`/`curr` current-branch aliases are **removed**. Every command that
targets a todo takes an explicit selector. Capture the Id from `mint` / `init`.

## CLI — implemented commands

Mechanism only. Policy (sizing, sequencing) lives in `frequentcommits` and
[`GROOMING.md`](GROOMING.md) / [`WORKING.md`](WORKING.md).

All ticket access goes through `todo.py`. Never `cat`/`jq`/`Read` a store file
or legacy `TODO.json` directly. Filtering after a sanctioned read is fine:
`todo.py read <id> | jq '...'`.

### Identity and listing

| Command | Behavior |
|---------|----------|
| `mint` | Mint Id + create store-only `groom` record (no git branch). Prints 64-hex Id |
| `init [--id <id>] [--summary=...]` | Promote `groom` → branch + `ready`, or fresh one-shot create. `--stay-on-parent` returns to previous branch. Refuses second ticket on current branch |
| `ls [--states=<expr>] [-s] [-t\|-tc\|-tu\|-g]` | List short id + summary. Hides FINAL by default |
| `read <selector>` | Print ticket JSON |
| `prompt <selector>` | Ancestor Summary/Body chain (farthest first) — startup context |
| `search <term>...` | Vector + lexical search; same state/column flags as `ls` |
| `embedders` | List selectable search embedders |
| `log <selector>\|ALL` | Graph of `Subtodos` tree (`-n`, `-v`, `-t`) |
| `basedir` / `repodir <selector>` | Print todo dir / main-checkout repo path |
| `rm <todoid> [--hard]` | Soft-delete (tombstone) or hard-delete; leaves git branch/worktree |

### Field access

| Command | Behavior |
|---------|----------|
| `get <selector> --summary\|--body\|--ac\|--state\|--actual-summary\|--parent\|--tag` | Exactly one flag; friendly wrapper over `get-json-path` |
| `get-json-path <selector> <path>` | Low-level path read |
| `set-json-path <selector> <path> [--file <path>]` | Low-level path write (stdin or `--file`). Store-only |
| `set <selector> [--summary=] [--body=] [--ac=] [--state=<s>] [--actual-summary=] [--parent=<id>] [--tag=] [--untag=]` | Patch fields and/or state. Store-only. Requires at least one field. `--parent` is make-it-so Parent list + INFO backlinks |
| `tag-add` / `tag-rm` / `tag-clear` | Manual tag ops (`set --tag`/`--untag` aliases for add/rm) |
| `resolveurl <path-or-url>` | Dereference permalink; no selector (todo is first path segment) |

### Subtodos and waiting

| Command | Behavior |
|---------|----------|
| `add-subtodo <parent> (--from-json=... \| --summary=...)` | Create child at tip of parent branch (no checkout). Requires `--summary` unless `--from-json`. Optional `--body`, `--ac`, `--id`, `--branch`, `--path-from-root`. Registers tracked subtodo; completes parent cursor as `start_subtodo` |
| `merge-subtodo <child-id>` | **Store bookkeeping only** after child is `done`. Locates parent via `Parent[0]`. Records `merge_subtodo` with parent branch tip sha. **Does not run `git merge`** — caller must already have integrated the child branch |
| `wait-for <id>...` | Poll until children reach target state (default `done`) |
| `wait-and-merge <subtodo-id>...` | Poll until `done`, then run `merge-subtodo` for each. **Does not git-merge branches** — same bookkeeping as `merge-subtodo` |

### Work items

| Command | Behavior |
|---------|----------|
| `work-item-add <selector> --summary=...` | Append not-done `task` |
| `work-item-insert <selector> --summary=...` | Insert task at cursor |
| `work-item-replace <selector> --summary=...` | Reword cursor task |
| `work-item-delete <selector>` | Delete cursor task |
| `work-item-read <selector>` | Cursor + `next` mechanism hint |
| `work-item-done <selector> [-m MSG] [--sha SHA] [--summary S] [--checkpoint]` | Complete cursor as `code` (or `--checkpoint`). Must run from a checkout of the todo’s branch |
| `is-done <selector>` | Exit 0 when no open work items |
| `last-sha <selector>` | Sha of last work item (branch tip attribution) |

### Maintenance and I/O

| Command | Behavior |
|---------|----------|
| `doctor <selector>\|ALL [--dry-run]` | Audit + repair (INFO backlinks, schema sweep, PR reconcile via `gh`) |
| `migrate-to-latest [--dry-run]` | Explicit record sweep to `SCHEMA_VERSION` |
| `import-json --from-json PATH \| --scan-refs` | Import legacy JSON into the store |
| `export-to-file <ids...>\|ALL [--remove[{=soft\|hard}]]` | Export round-trippable JSON under `<basedir>/storage/` |
| `web [selector] [--host] [--port] [--dump-html]` | Serve viewer + permalinks (default bind `localhost:8765`) |

### STUB (not automation)

| Command | Status | Behavior today |
|---------|--------|----------------|
| `ensure_worktree <todoid>` | **STUB** | Resolves todo and prints the *intended* path under `<todo-dir>/worktrees/<repo>/<branch>` with `created=false`. Does **not** run `git worktree add` |

Worktree create/remove remains a **manual** procedure in
[`WORKING.md`](WORKING.md#worktree-setup). Do not treat `ensure_worktree` as
having created a checkout.

### Minimal examples (verified forms)

```bash
TODO=skills/projectmanagement/todos/todo.py

# make (no branch)
ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."

# promote when ready to work
"$TODO" init --id "$ID" --stay-on-parent

# subtodo — either seed form
"$TODO" add-subtodo "$ID" --summary="Child research domain"
# or: "$TODO" add-subtodo "$ID" --from-json=./child-seed.json

# integrate child code, THEN bookkeeping
git merge "<child-branch>"   # on parent branch, in parent worktree
"$TODO" merge-subtodo <child-id>
# or after git merges: "$TODO" wait-and-merge <child-id>...
```

## State machine

`State` is an object with **exactly one** key. Mainline: `groom → ready →
working → done`. Subtodos the parent absorbs: `done → merged`. Interrupts:
`userneeded`, `stopped`.

| State | Value shape | Meaning |
|-------|-------------|---------|
| `groom` | `{}` | Minted; collecting data; branchless until `init` |
| `ready` | `{}` | Has a branch; not yet started |
| `working` | `{ "owner"?: string }` | Active (`expire` reserved, not settable) |
| `userneeded` | `{ "note"?: string }` | Blocked on user |
| `stopped` | `{ "note"?: string }` | User halt |
| `done` | `{ "last_commit"?: string }` | Complete on ticket branch |
| `merged` | `{ "merged_into"?, "last_commit"?, "pr"?, "merge_commit"? }` | Handed off (parent absorb **or** root PR) |
| `rejected` | `{ "pr"?, "note"? }` | PR closed unmerged |
| `fact` | `{}` | Memory anchor; never work without explicit user confirm |

Settable via `--state` (excludes `waiting` and `N/a`):

| State | Flags it takes |
|-------|----------------|
| `groom`, `ready`, `fact` | none |
| `working` | `--owner` |
| `userneeded`, `stopped` | `--note` |
| `done` | `--last-commit` |
| `merged` | `--merged-into`, `--last-commit`, `--pr`, `--merge-commit` |
| `rejected` | `--pr`, `--note` |

Passing metadata a state does not keep is an **error**.

`FINAL` = `done`, `merged`, `rejected` (hidden by default by `ls`/`search`).

**PR handoff (root todos only):** `done` → `set <id> --state merged --pr <N>`.
`doctor` reconciles merge_commit / `rejected` via `gh`. Subtodos with `Parent`
are skipped for PR reconcile.

**Working a `fact`:** before any `working` transition or worktree, stop and ask
the user. Never self-start a `fact`.

### State filters (`ls` / `search`)

Precedence: `--states` > `-s` (means `ALL`) > config `default_state_filter`
(default `ALL,-FINAL`).

Macros: `ALL`, `FINAL`, `PAUSING` (waiting, userneeded, stopped), `WORKING`,
`UNSTARTED` (groom, ready), `INFO` (fact).

## Record schema

Allowed top-level fields (unknown keys → doctor findings):
`AC`, `ActualSummary`, `Agent`, `BaseSha`, `Body`, `Branch`, `Id`, `Parent`,
`Scope`, `State`, `Subtodos`, `Summary`, `Tag`, `Tags` (legacy), `WorkItems`,
`create_dt`, `update_dt`, `_schema`, `_nextobjid`.

Required: `Branch`, `Id`, `State`, `Summary`.

### Identity

| Field | Behavior |
|-------|----------|
| `Id` | SHA-256 hex (64) of uuid1 raw bytes |
| `Branch` | `(Id[0:8] + "-" + kebab(summary words))[:32]` |
| `create_dt` / `update_dt` | RFC3339 `Z`; bump `update_dt` on every successful write |
| `_nextobjid` | objid allocation cursor (not a lock token) |

### objid

Every nested JSON object (except the root and the whole `State` subtree)
carries immutable `"objid": "0a3f"` unique within that todo. Writers stamp
them; doctor hard-fails missing/malformed/duplicate ids.

### Scope

Set at least one locator. Current keys:

| Key | Notes |
|-----|-------|
| `git_url` | Remote / canonical URL (preferred identity) |
| `path_from_root` | Path inside the repo |
| `branch` | Requires `git_url` when set |

`Scope.path_to_project` is **stripped** by record migration v6 and must not
appear in current examples.

### Summary, Body, AC, Tag

| Field | Type |
|-------|------|
| `Summary` | `{ "raw": "<title>" }` (+ optional embedder keys) |
| `Body` | `{ "raw": "<description>" }` |
| `AC` | string |
| `ActualSummary` | optional string at finish; reused by `merge-subtodo` |
| `Tag` | optional list of `{raw, manual, ...}`; manual sticky; auto-tagging dormant |

### WorkItems and invariants

| kind | fields | produced by |
|------|--------|-------------|
| `task` | `summary`, `done:false` | `work-item-add` / `work-item-insert` |
| `code` | `summary`, `sha`, `message`, `done:true` | `work-item-done` |
| `merge_subtodo` | `summary`, `subtodo_id`, `sha`, `done:true` | `merge-subtodo` |
| `start_subtodo` | `summary`, `subtodo_id`, `done:true` | `add-subtodo` |
| `checkpoint` | `summary`, `at_sha`, `message`, `done:true` | `work-item-done --checkpoint` |

Cursor = first not-done item (derived).

**Invariants** (tool + `doctor`; numbers kept stable):

1. A done item is `start_subtodo`, `checkpoint` (observational `at_sha`, never
   attributing `sha`), or a `code`/`merge_subtodo` that carries a `sha` plus a
   high-level description.
2. A not-done item is freetext (`task`) — a step or a prose list of not-yet-
   started subtasks — with `done:false`.
3. Done items form a prefix; the cursor moves monotonically down (list may grow).
4. One todo ↔ one branch; the ticket’s lifetime matches that branch’s role as
   the durable code line for the work (worktrees are ephemeral).
5. `BaseSha` records the branch’s initial sha, captured at branch creation
   (`init` / `add-subtodo`).
6. The last item of a done todo cannot be `start_subtodo` or `checkpoint` (or
   the null-sha sentinel); it must be a real `code`/`merge` commit so
   `last-sha` is the branch tip.
7. A todo `is-done` when it has no not-yet-done items.

`doctor` hard-checks shape via #1/#3/#6/#7 (and related kind/field rules). #2
is the not-done shape; #4/#5 are lifecycle/identity (BaseSha absence is a soft
warning when the sha is not in-repo).

### Permalinks

Emit objid links, not positional prose:

```
http://localhost:8765/<todoid>/objid/<objid>
```

Path grammar (served by `todo.py web`; CLI: `resolveurl`):

| Form | Means |
|------|-------|
| `/<todoid>` | whole record |
| `/<todoid>/summary/raw` | field (case-insensitive) |
| `/<todoid>/workitem/5/summary` | 0-based index |
| `/<todoid>/workitem/sha/883368/summary` | where-clause (4+ prefix) |
| `/<todoid>/objid/0a3f` | canonical object link |

Indexes are 0-based; bare segments are indexes (not bare hex). Prefer objid
over indexes when linking durable content.

### Minimal current skeleton

```json
{
  "Id": "8f3a2c1d9e7b4f6a5c0d8e2b1f4a6c3d7e9b0f2a4c6d8e0f1a2b3c4d5e6f7a8b",
  "Branch": "8f3a2c1d-fix-pico2w-env-sensor",
  "create_dt": "2026-06-22T16:00:00Z",
  "update_dt": "2026-06-22T16:00:00Z",
  "State": { "ready": {} },
  "Scope": {
    "git_url": "https://github.com/example/repo.git",
    "path_from_root": "firmware/pico2w"
  },
  "Summary": { "raw": "Fix pico2w environment sensor" },
  "Body": { "raw": "Sensor reads stale after sleep. Reproduce, fix driver init, add test." },
  "AC": "AHT20 returns fresh readings after 10 sleep/wake cycles; test in CI.",
  "WorkItems": [
    {
      "objid": "0000",
      "kind": "task",
      "summary": "Reproduce stale reading after sleep",
      "done": false
    }
  ]
}
```

WorkItem examples use `objid` + `kind`, never a foreign `id` field.

---

# Maintainer internals

## Schema versioning

One `todo_db.SCHEMA_VERSION` for table shape and record shape. Table migrations
run on sqlite connect. Record migrations: ordered `RECORD_MIGRATIONS`;
`migrate_record` applies pending steps and stamps `_schema`.

`todo.py migrate-to-latest` sweeps all records and advances store
`data_version`. `doctor` runs that sweep opportunistically (`migrated` count).

Notable record transforms (historical — see Compatibility):

- v6: `Chunks`→`WorkItems`, `Subtickets`→`Subtodos`, Parent dict→list, strip
  `Scope.path_to_project`
- v7: flat `Tags` → plural `Tag` elements
- v8: state renames `pre`/`pre-init`→`groom`, `init`→`ready`, `info`→`fact`

## Startup health

- Store behind → interactive warning to run `todo.py doctor ALL`
- Agent-framework detection → skills-buried warning on stderr (once per session)

## JSON path primitives

`read` / `get-json-path` / `set-json-path` are the lowest-level API. Higher
commands are special syntax over these paths. Triggers fire by changed path,
so `set --state done` and writing `State` via `set-json-path` share downstream
behavior.

## Automatic tags (dormant)

No cheap embedder is registered; `_recompute_auto_tags` returns 0. Search
backfills vectors lazily (`apple` on macOS). Auto-tagging re-arms when a cheap
semantic backend appears (related: ticket `91e28fd0`).

## Doctor checks (summary)

Hard findings fail (exit 1); soft warnings never fail. Includes: selector
resolution, allowed fields, State shape, references, wait-graph acyclicity,
subtodo merge completeness (tracked only; INFO excluded), WorkItem invariants,
objid integrity, PR disposition for root todos, unlock of stale locks, schema
sweep.

---

# Compatibility / history

**Legacy `TODO.json`:** import-only via `import-json --from-json` or
`--scan-refs`. Do not infer ticket presence from a worktree file. Doctor may
warn about leftover files. `TODO_USE_JSON=1` is legacy file mode.

**Renamed states:** `pre` / `pre-init` → `groom`; `init` → `ready`; `info` →
`fact`. Do not use old names in current examples.

**Removed selectors:** `self` / `curr`.

**`set-state` subcommand:** removed; use `set --state`.

---

# Deferred / planned

Non-normative. Do **not** put these in current dispatch tables.

| Item | Notes |
|------|-------|
| `todo.py new` | Mentioned historically as alias for `init` with JSON seed — **not implemented** |
| `ensure_worktree` automation | STUB today; future may create/remove trees |
| `waiting` state / dependency graph | In `VALID_STATES` / macros but not settable via `--state`; design deferred |
| `N/a` state | Present but not settable via `--note`/`--state` workflow |
| Stack across branches | Deferred |
| `working` lock / `expire` semantics | Reserved |
| Embeddings format canonicalization | Ongoing / deferred |
| Worktree add/list/remove CLI family | Future if parallel-checkout needs it |

Related skills: `frequentcommits` (WorkItem sizing policy),
`bookmark-management`, `project-lifecycle` (separate `TODOs.md` format — do not
merge without user direction).

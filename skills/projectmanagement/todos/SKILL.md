---
name: todos
description: >-
  Branch-bound todo task tickets managed through the todo.py CLI (one ticket
  per git branch; stored in the repo's .todo/ store -- sqlite.db or
  storage/*.json). TRIGGER: the user says "TODO", "todo", "ticket", "branch
  task", or asks to track/manage task state -- invoke immediately. Route ALL
  ticket access through todo.py; never read or write TODO.json directly or
  query the store by hand. The full workflow,
  CLI, and schema live in this skill body and load only when triggered.
disable-model-invocation: false
---

# Todo tickets

status: living document

Associative memory for pruned contexts: a task ticket that lives with a git
branch. One branch carries **zero or one** ticket in the store -- a JSON object
in `<main-checkout-root>/.todo/` (sqlite.db or storage/*.json backend; the
record is JSON either way). Every command addresses a todo by explicit Id;
there is no current-branch (`self`/`curr`) selector. Legacy TODO.json is
import-only.

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
| No silent skips | Do not mark the parent `done` while any subtodo is still `ready` or `working`, or `done` but not yet `merge-subtodo`'d on the parent. |
| Merge is bookkeeping + git | After the child's git branch is merged (or absorbed), run `merge-subtodo <child-id>` -- it locates the parent through the child's `Parent[0]` ref (no checkout) -- so `Subtodos[].State` becomes `merged`. |
| Parent synthesis last | Parent `done` only after all subtodos are `merged` (or explicitly waived by the user). |

**Normal loop:**

1. Parent `working`; file subtodos with `add-subtodo <parent-id>` (each records a `start_subtodo` item and advances the parent cursor).
2. Per child (often one subagent each): work the child in its worktree through the lifecycle loop (`set <child-id> --state working`, poll and work items to `is-done <child-id>`, `set <child-id> --state done`).
3. Parent: `wait-for` / `wait-and-merge` (or `merge-subtodo` each) until every child is `merged` on the parent record.
4. Parent works any remaining synthesis WorkItems to `is-done`, then `set <parent-id> --state done`.

**Surfacing blockers:** If a child cannot finish without the user, `set <child-id> --state userneeded --note=...`, then set parent `userneeded` with which child blocked. Never leave a child in `ready`/`working` indefinitely without escalating.

**Anti-patterns (do not do this):**

- Landing all code on the parent branch while child branches stay `ready`.
- Marking children `done` from the parent checkout without working the child branch.
- Marking parent `done` when `todo.py read <parent-id> | jq -r '.Subtodos[].State'`
  still shows `ready` or `done` (unmerged).

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
- `todo.py set <child-id> --parent <id>` (repeatable) is a **make-it-so** write of that
  list: the child's `Parent` becomes exactly the listed refs (order preserved,
  blanks skipped; bare `--parent=` clears). It also syncs follow-only **INFO
  back-links** into each desired parent's `Subtodos` (`State: "INFO"`) and
  **removes** INFO back-links from former parents that are no longer listed, so
  links stay navigable both ways (HATEOAS) without any merge obligation.
  Tracked/mergeable `Subtodos` rows (from `add-subtodo`) are never removed.
  Use it to hang a todo off an existing one (even an old, done, or unrelated
  todo) for context/bookkeeping -- typically after the parent is finished, not
  while working it. The INFO link is *not* a tracked subtodo: it is excluded
  from merge-completeness, and `doctor` refreshes its best-effort `Summary`
  when sweeping. For a real subtodo the parent must merge, use `add-subtodo`
  instead.

INFO back-links are best-effort and same-repo (a write keys by the current
repo). A child created before this behavior, or one whose parent lives in
another repo at creation time, is healed by `doctor` (which re-establishes the
back-link from the child's `Parent` ref) the next time it runs in the parent's
repo.

**First thing a working agent should do:** run `todo.py prompt <id>`. It
walks the `Parent` chain up and concatenates each todo's
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

### Model capability targeting (generic tiers)

Every delegated unit -- a subtodo, or the work behind a parent-local WorkItem -- gets a
capability tier chosen by **task shape**, not by model brand. Tier names are generic so the
policy survives vendor and model-generation churn; map whatever models are current into the
tiers at time of use.

| Tier | Generic meaning | Typical work |
|------|-----------------|--------------|
| HICAP | the vendor's flagship reasoning model; expensive, spend sparingly | architecture and cross-repo decisions; hazard-dense FIRST implementations; ambiguous debugging |
| MIDCAP | strong general coding model; the default workhorse | pattern-following code; skill-scripted checklists; inventories; test authoring |
| LOCAP | small, fast, cheap model | run-and-report verification; formatting; trivial mechanical edits |

Example mapping (2026, Anthropic): HICAP = Fable/Opus, MIDCAP = Sonnet, LOCAP = Haiku. The
mapping is an example, not part of the policy -- re-derive it per vendor and generation.

Targeting rules:

1. **Default MIDCAP.** Escalate or de-escalate on task shape; never assign HICAP for
   prestige or "importance" alone.
2. **HICAP only where ambiguity or hazard density concentrates -- and make it bounded.**
   The canonical shape: spend HICAP ONCE to land an exemplar (one class, one pattern, one
   design sketch, with its guard tests), then the bulk roll-out is genuinely mechanical and
   drops to MIDCAP. Keep the exemplar item and the roll-out item separate; merging them
   destroys the parsimony.
3. **Human answers are free.** Product decisions cost zero model tokens when asked during
   grooming; do not spawn a HICAP planner to guess what the user can simply decide. A
   planning item often shrinks to "write down the ratified decisions".
4. **Parent-local != parent-model.** Bookkeeping (cursor, merges, state) stays in the
   orchestrating session, but the work behind a parent-local item may still be delegated to
   a cheaper subagent.
5. **LOCAP is run-and-report, with an escalation path.** Verification (test suites,
   linters, guards) runs LOCAP; on red, escalate the FIX (not the re-run) to whatever tier
   the failure demands.
6. **Escalate on discovered ambiguity.** A MIDCAP/LOCAP agent that hits an unresolved
   design question stops and escalates rather than guessing.
7. **Miss-cost guard.** Do not de-escalate to LOCAP where a silent miss is expensive even
   if the work looks mechanical: cross-repo registration checklists, migrations against
   populated DBs, anything whose failure mode is "silently incomplete".
8. **Tag it.** Prefix each WorkItem summary / subtodo with the tier (`[HICAP]`, `[MIDCAP]`,
   `[LOCAP]`), optionally pinning a concrete model (`[MIDCAP/sonnet]`). State the chosen
   tier when creating each subtodo.

**Workflow shape (the driver loop):** a HICAP session DRIVES -- it grooms the ticket,
ratifies design decisions with the user, and decomposes the work into bounded items;
MID/LOCAP agents IMPLEMENT those items (typically fork subtodos); the HICAP driver
REVIEWS each merge and re-grooms before the next fan-out. Implementation never starts
from an ungroomed item.

## Storage (the store: sqlite or json-dir)

Todo directory resolution (once per `todo.py` invocation; no mixing paths). The
repo anchor is the repo's **MAIN checkout root** -- the primary working tree, NOT
the current linked worktree -- so every worktree of a repo shares ONE store in the
core checkout. (`git worktree list` lists the main worktree first; bare/no-checkout
hosting is out of scope.)

1. `$TODO_DIR` when set and it holds a store (`config.json`, `sqlite.db`, or `storage/`)
2. `<main-checkout-root>/.todo/` when that holds a store
3. `$HOME/.todo/` when that holds a store

If none exist, create under the first applicable default: `$TODO_DIR`, else
`<main-checkout-root>/.todo/`, else `$HOME/.todo/`. Db and worktrees both live
under the chosen directory. Note: the storage anchor is the main checkout root;
git *operations* (branch create/checkout/commit) still happen in the current
worktree.

| Item | Location | Notes |
|------|----------|-------|
| Tickets | `<todo-dir>/sqlite.db` or `<todo-dir>/storage/*.json` | Two interchangeable store backends behind one `todo_storage` DSN (layout-inferred when config.json lacks one); the ticket is a JSON object either way, keyed by (repo_path, branch); `todo.py ls` lists them |
| Embeddings | in the ticket JSON; sqlite backend also mirrors a derived embeddings index | Cheap (hash) stamped in ticket JSON on write; others backfilled on search. `read` merges every embedder found in the index into its output regardless of which path wrote it, elided to its first two elements |
| Worktrees | `<todo-dir>/worktrees/` | Nested by repo path |
| Legacy JSON | git TODO.json | Import only: todo.py import-json |

Set TODO_USE_JSON=1 for legacy file mode. Search embedders: `todo.py search
--embedder` (comma list; default all non-hidden; see `todo.py embedders`).

### Schema versioning and `migrate-to-latest`

There is ONE schema version, `todo_db.SCHEMA_VERSION`, shared by the sqlite
table shape and the record (ticket JSON) shape. Every schema change bumps it by
one and registers its migration; a change that touches only one axis leaves the
other a no-op. Two migration paths ride that single number:

- **Table** migrations run automatically on every sqlite connect
  (`todo_db.migrate`).
- **Record** migrations are an ordered registry, `todo_db.RECORD_MIGRATIONS`
  (version -> transform). `todo_db.migrate_record(todo)` applies every pending
  step ascending and stamps `todo["_schema"]`. The shared v6 transform (legacy
  field renames: `Chunks`->`WorkItems`, `Subtickets`->`Subtodos`, singular
  `Parent` dict->list, strip `Scope.path_to_project`) is what
  `normalize_todo_schema` delegates to on ordinary reads (without stamping).

`todo.py migrate-to-latest` sweeps every record in the resolved store (both
backends, via the store abstraction), migrates each, writes back the changed
ones, and advances the store's `data_version` marker (a sqlite `data_version`
table, or a `.data_version` sidecar for the file-dir backend) to
`SCHEMA_VERSION`. It is idempotent (`--dry-run` reports counts without writing).
`data_version` is DISTINCT from the table `schema_version`: it records how far
the RECORDS have been swept. `doctor` owns the sweep: it runs `migrate-to-latest`
opportunistically (a cheap no-op when already current, reported as `migrated`),
so the sweep rides normal maintenance rather than a command a human must
remember. The `migrate-to-latest` subcommand remains for an explicit or
`--dry-run` sweep. A cheap startup check warns (interactive terminals only)
`run 'todo.py doctor ALL'` when the store is behind. To add a schema change: bump
`SCHEMA_VERSION`, add any table DDL to `migrate`, add any record transform to
`RECORD_MIGRATIONS` at the new version -- `doctor` sweeps it in.

**Startup skills-doctor check (agent install-health).** A second cheap startup check runs the
*inverse* way to the store-behind nudge: when `todo.py` is invoked by an **agent framework**
(detected from env -- `AGENT=<name>` first, else `CLAUDECODE`/`CLAUDE_CODE_*`, `CODEX_*`, `CURSOR_*`,
`OPENCODE_RUN_ID`), it verifies that framework can actually *discover* its skills and complains on
stderr (the pipe the agent reads back) if any are installed too deep for its scanner -- e.g. a skill
at `<root>/<group>/<sub>/SKILL.md` when Claude Code only scans one level under `~/.claude/skills`
(unless a top-level sibling symlink already exposes it). It is gated on **framework detection, not
`isatty`** (an agent's stderr is not a tty, so the store-behind gate would wrongly hide it), and
fires **once per session**. Frameworks whose discovery rules are not yet encoded (cursor,
chatgpt/codex, ...) emit a `FIXME` asking for them; a plain shell / unknown caller stays silent. See
`_warn_if_skills_buried` / `_detect_agent_framework` / `_buried_claude_skills` in `todo.py`.

## CLI (`todo.py`)

AWS-style subcommands live beside this skill as
[`todo.py`](todo.py). Demo API first; efficiency is not the goal.

`todo.py` is **mechanism** only: it stores and mutates todos. *Policy* -- how
to size, sequence, and refine work into WorkItems -- lives in `frequentcommits`.
Do not push sizing or sequencing rules into the tool.

All `TODO.json` access goes through this CLI, even if the requested operation is
"just print it" or "check whether it exists." Do not use `cat`, bare `jq` on
`TODO.json`, `ReadFile`, `git show`, shell tests, or ad hoc JSON parsing against
`TODO.json` directly. Treat `TODO.json` as a temporary storage implementation
hidden behind the `todo.py` interface. Filtering after a sanctioned read is fine:
`todo.py read <id> | jq '...'`.

| Command | Status | Behavior |
|---------|--------|----------|
| `todo.py mint` | implemented | Mint a fresh ticket `Id` (uuid1 -> SHA-256 of its raw bytes), collision-checked across the repo, AND create its record: state `groom` (collecting data), placeholder `Branch` (`Id[0:8]`), **no git branch, no commit** (store-only). Prints the 64-hex Id. Fill it via `set <id>`; `init` when ready to work |
| `todo.py read <selector>` | implemented | Print the ticket JSON for `<selector>`: any **4+ hex unambiguous prefix**, or the full digest. Resolution scans the store directly (cross-repo, no catalog); it falls back to a current-repo ref scan only when the store has no hit. Local-first: remote fetch is feature-flagged off (`FETCH_ENABLED`) |
| `todo.py search <term>...` | implemented | Vector + lexical ticket search over one or more terms, google-style: each term is embedded and matched independently and the per-term scores add. A term is the unit of embedding -- quote a phrase (`todo search "bh 791"`) to match it whole; unquoted words (`todo search bh 791`) match individually. Hides FINAL (done, merged) by default; `-s` shows all states, `--states=<expr>` filters (UPPERCASE macros ALL/FINAL/PAUSING/WORKING/UNSTARTED/INFO plus lowercase state names, comma/`+`/`-`, e.g. `WORKING+PAUSING` or `ALL,-done`). `-n` limit; `--embedder` comma list (default all non-hidden), `--dry-run`, `--tag` comma list (keep only todos with a matching plural `Tag` element, case-insensitive), and the `-s/-t/-tc/-tu/-g` display-column selectors shared with `ls` |
| `todo.py prompt <selector>` | implemented | Concatenate a todo and its `Parent` chain (Summary/Body) into one startup prompt, farthest ancestor first, target last -- zero-context agent reads WHY down to WHAT. Read-only |
| `todo.py embedders` | implemented | List selectable search embedders (non-hidden) with cheap/expensive |
| `todo.py import-json` | implemented | Migrate legacy JSON: --from-json PATH or --scan-refs |
| `todo.py migrate-to-latest [--dry-run]` | implemented | Sweep every record in the resolved store to `todo_db.SCHEMA_VERSION` via `todo_db.migrate_record` (both backends), write back changed records, and advance the store's `data_version` marker. Idempotent; `--dry-run` reports scanned/would-migrate counts without writing. See "Schema versioning" above |
| `todo.py ls [--states=<expr>] [-s] [-t\|-tc\|-tu\|-g]` | implemented | Print `<id[0:8]>  <summary>` per todo -- where-to-find-it only; use `read <id>` for content. Hides FINAL (done, merged) by default; `-s` shows all states, `--states=<expr>` filters (macro grammar; see `search`). Column flags: `-s` State, `-t`/`-tc` create-time, `-tu` update-time, `-g` Tags (leftmost, in flag order, summary last, right-padded); with any column flag rows sort ascending by the leftmost column, else insertion order |
| `todo.py get-json-path <selector> <path>` | implemented | Low-level path read. Prints one value from a selected todo as JSON. `<path>` is the internal dot-path syntax, e.g. `Body.raw` or `WorkItems.0.summary`. |
| `todo.py get <selector> [--summary\|--body\|--ac\|--state\|--actual-summary\|--parent\|--tag]` | implemented | Friendly-field-name wrapper: pass exactly one flag and it expands into the matching `get-json-path <selector> <path>` call (`Summary.raw`, `Body.raw`, `AC`, `State`, `ActualSummary`, `Parent`, `Tag` respectively) and prints that value. `<selector>` is required, same as `set`. For any other path use `get-json-path` directly. |
| `todo.py set-json-path <selector> <path> [--file <path>]` | implemented | Low-level path write. Sets one JSON path to a value read as JSON from `--file` or stdin. Store-only: no branch checkout, no commit -- works on a branchless `groom` todo. The general way to replace `WorkItems` or seed a whole plan. |
| `todo.py init [--id <id>] [--summary=...]` | implemented | Run when ready to WORK the todo. **Promote mode** (`--id` of an existing `groom` todo): create the local branch from its `set`-finalized `Branch`, move it to state `ready`, capture `BaseSha` (invariant #5). **Fresh mode** (`--summary`, no existing record): mint (or accept `--id`) + create branch + skeleton in one call (backward-compatible). Refuses when the current branch already has a ticket. `--agent-type`/`--session-id` (or `$TODO_AGENT_TYPE`/`$TODO_SESSION_ID`) record the creating agent. Fresh mode also accepts `set`'s edit args (init-then-set) except `--parent` (use `set <id> --parent` after). `--stay-on-parent` returns to the previous branch after creating the todo branch |
| `todo.py ensure_worktree [<selector>]` | STUB | Will materialize a git working tree for the todo's branch (idempotent) so code can be worked, and is meant to be called implicitly whenever a flow touches code; the tree may become ephemeral later. STUB today: resolves the todo and prints the INTENDED path (`<todo-dir>/worktrees/<repo>/<branch>`) with `created=false`; does not run `git worktree add` yet. Selector is a 4+ hex Id prefix or the full digest |
| `todo.py add-subtodo <parent> --from-json=...` | implemented | Create a child todo under the parent selected by id: the child git branch is created at the tip of the parent's branch (no checkout, requires the parent branch to exist locally), `BaseSha` captured, both records written through the store, child registered in the parent's `Subtodos`. Completes the parent's cursor work item as a typed `start_subtodo` done item and advances the cursor. Requires the store (legacy TODO_USE_JSON mode is import-only) |
| `todo.py merge-subtodo <child-id>` | implemented | After child is `done`: locate the parent through the child's `Parent[0]` ref, set the child `merged`, update parent `Subtodos[].State` to `merged` -- all store-only, no checkout. Records a typed `merge_subtodo` done item on the parent's cursor whose sha is the parent branch's tip (the caller's real git merge, which must already have landed) and advances the cursor. The work item summary comes from the child's `ActualSummary` (falling back to `Summary.raw`) |
| `todo.py set <selector> [--summary=] [--body=] [--ac=] [--state=<s>] [--actual-summary=] [--parent=<id>] [--tag=] [--untag=]` | implemented | Patch `Summary.raw`/`Body.raw`/`AC`/`ActualSummary`, add/remove MANUAL plural `Tag` elements (`--tag`/`--untag`, repeatable -- aliases of `tagadd`/`tagrm`; downcased, deduped, field dropped when empty), and/or transition `State` (requires at least one field). `<selector>` is required and positional: an Id prefix or full digest (works equally on a branch-bound todo or a branchless `groom` todo from `mint`). The write is store-only -- no checkout, no commit. For a `groom` todo, `--summary` also refreshes the `Branch` label. `--state <s>` (with metadata `--note`/`--last-commit`/`--merged-into`/`--owner`) **replaces the removed `set-state` subcommand**; valid states `groom`, `ready`, `working`, `userneeded`, `stopped`, `done`, `merged`, `fact`. `--parent <id>` (repeatable) is a **make-it-so** write of the `Parent` list: desired end-state replaces the child's refs, adds/refreshes follow-only `INFO` back-links on desired parents, and removes `INFO` back-links from former parents no longer listed (tracked subtodos untouched); bare `--parent=` clears. `EDIT` free-text captured from `$VISUAL`/`$EDITOR`/`vi` (non-interactive `EDIT` exits 1). |
| `todo.py rm <todoid> [--hard]` | implemented | Soft-delete a todo from the store: a recoverable tombstone (`deleted_tickets` row in sqlite, or an `<id>.deleted` file in a json-dir store) -- the same removal `export-to-file --remove` performs, without writing an export file. `--hard` deletes permanently (no recovery tool). The git branch and any worktree are left intact. |
| `todo.py tagadd <selector> <tag>...` | implemented | Add MANUAL tags to the selected todo's plural `Tag` field: each becomes a `{raw, manual: true}` element (stripped, downcased, deduped). Idempotent; store-only write. `set <id> --tag` is an alias |
| `todo.py tagrm <selector> <tag>...` | implemented | Remove MANUAL tags from the selected todo's `Tag` field (case-insensitive match on `raw`); automatic (`manual: false`) tags are never removed here (they are `doctor`'s to manage). Drops the field when empty. `set <id> --untag` is an alias |
| `todo.py work-item-add <selector> --summary=...` | implemented | Append a not-done `task` work item (`{kind:"task", summary, done:false}`) to the selected todo's `WorkItems`. Store-only, so it works on a branchless `groom` todo (incremental plan seeding) |
| `todo.py work-item-done <selector> [-m MSG] [--sha SHA] [--summary S]` | implemented | Complete the cursor (first not-done) item as a typed `code` item and advance the cursor. Must run from a checkout (worktree) of the todo's branch -- it binds a code commit to the work item -- and errors otherwise. Post-condition: branch fully committed. Dirty tree: commits `git add -A` (message = `-m` or the work item summary), records new HEAD sha. Clean tree: records HEAD, or a `--sha` that must equal HEAD (mismatch exits 1). Adds no bookkeeping commit, so the sha stays branch HEAD (#6). Stores the full commit message on the node as `message` so the WorkItems trail records what actually changed -- pass a descriptive `-m` (outcome + files/tests added) |
| `todo.py work-item-read <selector>` | implemented | Print the cursor work item (first not-done), its index, whether the todo is done, and a `next` object -- the deterministic mechanical command to advance the loop (`{action, command}`), including the finish sequence when done. `next` is a mechanism hint, not policy; a plain task defaults to `work-item-done` but may instead be split or turned into a subtodo per the dispatch table |
| `todo.py work-item-insert <selector> --summary=...` | implemented | Insert a not-done `task` at the cursor so it becomes current, pushing the frontier down (used to explode a step into finer steps); appends when there is no open item |
| `todo.py work-item-replace <selector> --summary=...` | implemented | Rewrite the cursor task's freetext summary, leaving it not-done |
| `todo.py work-item-delete <selector>` | implemented | Delete the cursor (not-done) work item |
| `todo.py is-done <selector>` | implemented | Report whether the todo has no not-yet-done work items (#7); exits 0 when done, 1 when not |
| `todo.py last-sha <selector>` | implemented | Print the sha of the last work item, which is the last commit on the branch (#6) |
| `todo.py wait-for <id>...` | implemented | Poll selected child todos until they reach a target state, default `done`, without direct file reads. Initial implementation polls through todo selectors; better signaling can follow real usage. |
| `todo.py wait-and-merge <subtodo-id>...` | implemented | Poll child todos until `done`, then run merge bookkeeping for each child. |
| `todo.py doctor [<selector>\|ALL] [--dry-run]` | implemented | Audit schema, references, wait graph, and the WorkItem invariants (#1/#3/#6/#7), **and repair parent back-links**: for each `Parent` ref on the audited todo, re-establish a follow-only `INFO` back-link in the parent's `Subtodos` (best-effort, same-repo, store only). Repair runs by default; `--dry-run` reports intended repairs without writing; selector `ALL` sweeps the whole corpus instead of one selector. Repair also sweeps records to the latest schema (`migrated` count) and recomputes missing AUTOMATIC `Tag` elements from Summary+Body (trust-existing; `auto_tags` count; manual tags untouched). Two finding tiers: hard `findings` (fail, exit 1) for shape violations; soft `warnings` (never fail) for checks needing an absent subbranch or other repo |
| `todo.py log <selector>\|ALL` | implemented | Render the ticket graph (the `Subtodos` tree) for `<selector>` (a 4+ hex Id prefix, the full digest, or `ALL`) in git-log `--graph --oneline` style: `* <Id[0:8]> <summary>  [<state>]` with `\|` rails. Selector `ALL` renders every root as a forest; `-n N` caps lines; `-v` lists each ticket's branch commits (its frequentcommit trail); `-t` adds timestamps (ticket update time on nodes, commit date on the `-v` lines). Graph structure is from `TODO.json` via todo.py's readers; only `-v`'s commit lines read git. Output truncates to terminal width on a TTY, full when piped. |
| `todo.py new --summary=... --body=...` | planned | alias for `init` with optional JSON seed |

Run from inside the target repo (`cd` there first; there is no `--repo` flag --
repo root is the current directory's `gitroot`):

```bash
chmod +x skills/projectmanagement/todos/todo.py   # once
skills/projectmanagement/todos/todo.py read 8f3a2c1d
```

## Selectors and path primitives

Selectors are the public way to name a todo. Implemented selectors are the full
`Id` and unambiguous 4+ hex `Id` prefixes:

| Selector | Meaning |
|----------|---------|
| `<id-prefix>` | Any unambiguous 4+ hex prefix of the 64-hex `Id` (or the full digest). |
| `ALL` | Every todo in the corpus (uppercase, matching the `--states=ALL` macro convention); recognized by `doctor` and `log` in place of a single selector. |

The former `self`/`curr` current-branch aliases are REMOVED: resolving a todo
from the checked-out branch was a mistake. Every command takes an explicit id;
capture the Id when you mint/init and address the todo by it.

The lowest-level API should be:

| Primitive | Behavior |
|-----------|----------|
| `read <selector>` | Print the whole todo. |
| `get-json-path <selector> <path>` | Print one internal dot-path value as JSON. |
| `set-json-path <selector> <path> [--file <path>]` | Set one internal dot-path value from JSON on stdin or `--file`. |

Filter/project with the system `jq` on `read` stdout (not a `todo.py` subcommand):

```bash
todo.py read <selector> | jq '...'
```

Higher-level commands are special syntax for these primitives, plus triggers.
Triggers fire by changed path, not by command name, so `set <id> --state done` and
`set-json-path <id> State` (with `{"done": {}}` on stdin) share the same
downstream behavior.

## Placement and branch rule

| Rule | Value |
|------|-------|
| Storage | `<main-checkout-root>/.todo/` (sqlite and/or `storage/*.json`); repo_path is the main checkout, not a worktree |
| Main checkout branch | Always `master` (or `main`/`dev` if that is the repo's default) while any todo is being worked |
| Todo code checkout | **Exclusive worktree** for the todo's branch -- never `git checkout` the todo branch in the main checkout |
| Per branch | 0 or 1 ticket |
| Legacy file | TODO.json -- import only; doctor warns |
| Conflict | If `TODO.json` already exists on the branch, **resume or finish** it; do not create a second ticket, rename, or use subdirs |

Typical pairing: create the branch when you open the ticket; set `Branch` and
`Scope.branch` at that point (the branch may exist only locally until pushed).

**Lifecycle:** `TODO.json` lives with the branch. Cleanup, archival, and
post-`done` moves are out of scope -- do not delete or relocate the file as part
of this workflow unless the user explicitly asks.

### Why main stays on master (storage vs code)

`.todo/storage` (and related exports) are **versioned in the main checkout**. If
you check out a todo branch *in that tree*, every ticket-storage churn becomes a
commit (or dirty path) on the *todo* branch. That couples unrelated tickets into
feature-branch history and makes merges fight over `.todo/storage/*`.

Wanted shape today (separate longer-term storage versioning may come later):

- **Main checkout** stays on `master` and is where storage is committed when we
  intentionally version tickets.
- **Todo branch** is checked out **only** as a linked worktree; code and
  branch-local commits live there; do not land storage-only noise on that branch.

## Worktree placement

**Worktrees are ephemeral. The durable asset is the repo and the TODO's
branch.** The ticket record lives in the shared store; the code branch lives in
the repo (and is pushed to the remote) -- that pair is the identity. A worktree
is a disposable checkout used to work that branch; create and delete them
freely, and never treat a worktree path as where a todo "lives." Find todos by
repo + branch (`todo.py ls` / `todo.py read <id>`); use `git worktree list` only
to locate a branch's current checkout when one exists.

### Hard rule: work todos only in worktrees

**Every working todo (top-level or subtodo) is checked out exclusively into a
dedicated git worktree.** Do **not** `git checkout <todo-branch>` in the main
repodir.

Before any code or ticket work on a todo (`set <id> --state working`,
`work-item-done <id>`, edits under the repo, etc.), **verify both**:

1. **Main checkout is on `master`** (or the repo default). From the main
   checkout root (first path in `git worktree list`):
   `git -C <main-checkout-root> branch --show-current` must be `master`.
2. **CWD is a linked worktree of the todo's branch**, not the main checkout:
   `git rev-parse --show-toplevel` ≠ `<main-checkout-root>`, and
   `git branch --show-current` is the todo's `Branch`.

If either check fails: stop. Create/reuse the worktree (below), `cd` into it,
put the main checkout back on `master` if needed, then re-verify. Do not proceed
while the main tree is on the todo branch.

```bash
# Main checkout (storage anchor) must stay on master
MAIN=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
git -C "$MAIN" branch --show-current   # expect: master

# Work happens only in a linked worktree of the todo branch
git rev-parse --show-toplevel          # must NOT equal $MAIN
git branch --show-current              # expect: <todo Branch>
```

`todo.py init --stay-on-parent` creates the branch without leaving you on it in
the main tree -- prefer that when filing from the main checkout, then
`git worktree add` and work there.

### Todo / subtodo worktree lifecycle (open on entry, tear down on done/merged)

A **todo is worked in its own dedicated git worktree**, so the main checkout
(and parent/siblings) never share that checkout:

- **On entry** (an agent begins working a todo -- typically `set <id> --state
  working`): create a fresh worktree for the todo's branch under the placement
  convention below (`git worktree add <todo-dir>/worktrees/<repo-path>/<branch>
  <branch>`) and `cd` into it. Reuse an existing worktree for that branch if
  `git worktree list` already shows one; never move it. Confirm the main
  checkout is still on `master` before continuing.
- **On entering `done` or `merged`** (the todo's final commit is in -- `is-done <id>`
  is true and the final code/merge commit has landed; the state write itself is
  store-only): tear the worktree
  down (`cd` out, then `git worktree remove <path>`). Teardown removes only the *checkout*; the
  branch and its commits survive for merge/handoff. If the tree is dirty, the todo is
  not actually done -- finish or surface it before removing.

**INVARIANT: `done` and `merged` imply no live worktree.** Tearing the worktree down is a *defining
property* of entering either terminal state, not an optional cleanup step: `set <id> --state done` /
`set <id> --state merged` MUST be followed by `git worktree remove` of that todo's worktree. A todo left
in `done`/`merged` with its worktree still standing is an invariant violation; the next agent (or a
`doctor` sweep) should remove the orphaned worktree. The branch is retired *separately* -- see the
delete gate below.

The branch is the durable asset; the worktree is scratch space that exists only
for the span from entry to the terminal state.

**Branch retirement (the delete gate).** Tearing down a *worktree* is always safe
-- it removes only a checkout; the branch and its commits survive. DELETING a
branch is gated on **handoff to its PARENT / upstream branch -- NOT on reaching
`dev`/`master`.** A branch is retireable once its work has landed upstream:

- a **subtodo** hands off to its **parent todo's branch** (via `merge-subtodo` --
  a git merge of the child);
- a **top-level todo** hands off to whatever upstream branch it fed -- the branch
  the work was handed to (e.g. a diagnosis todo whose fixes were cherry-picked
  onto a feature branch).

The handoff can be a git merge OR a cherry-pick / equivalent-content absorption --
what matters is that the WORK is upstream, not git-ancestry. Once handed off, the
branch is disposable scaffold; delete it (`git branch -D`, since a cherry-pick
handoff won't register as "merged"). Do **not** gate deletion on the work reaching
`dev` -- that is often many merges upstream and is not this branch's concern.

**Existing worktrees are found with `git worktree list` and are never moved.**
Only *new* worktrees follow the placement convention below; the path is never
passed on the command line -- it is a creation convention, not a lookup key.

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

**Gate (working an existing todo):** verify main-on-master + CWD-is-todo-worktree
(see **Hard rule: work todos only in worktrees**). Do not edit code or advance
WorkItems until both hold.

```bash
# --- verify layout (required before working a todo) ---
MAIN=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
git -C "$MAIN" branch --show-current          # must be master
test "$(git rev-parse --show-toplevel)" != "$MAIN"   # must be in a linked worktree
git branch --show-current                     # must be the todo Branch

# --- then ---
git rev-parse --show-toplevel        # confirm worktree root; cwd should be here
todo.py init --summary="..."         # refuses if current branch already has a ticket; prints the Id -- capture it
todo.py set <new-id> --parent <id>   # hang this todo off an existing one (INFO back-link)
todo.py init --id <id> --stay-on-parent      # promote without parking main on the todo branch
todo.py read <known-id-prefix>        # load a known ticket; do not read TODO.json directly
todo.py prompt <id-prefix>            # WHY->WHAT startup context: the todo + its Parent chain
```

Use `init`'s refusal as the guard against creating a second ticket on the branch.
`init` prints the new todo's `Id` -- capture it; every later command addresses
the todo by that id (there is no current-branch selector).

## JSON access

- Keep the ticket record **well-formed JSON** at all times by using `todo.py`
  for every read and write. The CLI owns parsing, validation, normalization,
  timestamps, and store writes.
- **Never** read field values by eyeballing JSON pasted into chat, direct file
  reads, `cat`, bare `jq`/`git show` on `TODO.json`, or shell tests. Even
  read-only stdout display is `todo.py read <id-prefix>` (optionally piped to
  `jq` for filters).
- **Never** hand-edit an existing `TODO.json` in the model context. Use `todo.py
  set <selector>` (fields and/or `--state`), work-item commands, `add-subtodo`, `merge-subtodo`,
  or `todo.py set-json-path <id> <jsonpath>` (value as JSON on stdin or `--file`).
- Temporary seed JSON files passed to `--from-json` or `set-json-path --file` are
  inputs to the CLI, not direct `TODO.json` access. They may be authored as
  ordinary files, then consumed by `todo.py`.

```bash
# read the full todo JSON
todo.py read 8f3a2c1d

# read one field
todo.py get-json-path 8f3a2c1d Summary.raw

# project/filter with system jq (not a todo.py subcommand)
todo.py read 8f3a2c1d | jq '.Id, (.State | keys[0]), .Summary.raw'

# patch simple fields
todo.py set 8f3a2c1d --ac="new criteria"

# patch any JSON path on any todo by id; value is JSON read from stdin (or --file)
printf '%s' '"new body"' | todo.py set-json-path 8f3a2c1d Body.raw

# transition state; todo.py updates update_dt; the write is store-only (no commit)
todo.py set 8f3a2c1d --state working --owner=agent
```

## Id minting

`Id` is **not** the raw UUID string: it is the SHA-256 (64-hex) of a **uuid1**'s
raw bytes -- the one fixed version, mixing host MAC, time, and a random clock
sequence. The full digest is the canonical `Id`; `Id[0:8]` is the git-like short
id on the branch (8-or-more, your call). The tool owns minting and the collision
search -- do not hand-roll it:

```bash
TODO=skills/projectmanagement/todos/todo.py
ID=$("$TODO" mint)        # collision-checked across the repo; ALSO creates the record
# branch prefix is ${ID:0:8}
```

### Two-phase lifecycle: "make a todo" (mint + set) vs "work the todo" (init)

Creation is split into a data-collection phase and a work phase:

- **Make a todo** = `mint` then `set <id>`. `mint` creates a record in state
  `groom` (still collecting data), with **no git branch** and no commit
  (store-only). `set <id>` fills its fields; while `groom`, changing
  `--summary` also finalizes the `Branch` label. Do this whenever the user says
  "make a todo" -- it does NOT touch git or switch branches.
- **Work the todo** = `init`. Run it when the user signals the design is ready
  and it is time to WORK the todo (often implicit, explicit when they say "work
  the todo"). `init --id <id>` PROMOTES the `groom` record: it creates the git
  branch (from the `set`-finalized `Branch`) and moves it to state `ready`
  (started or not). No `--summary` needed -- it is already on the record.

```bash
TODO=skills/projectmanagement/todos/todo.py
# make a todo (design phase; no branch created):
ID=$("$TODO" mint)                                   # -> groom record + Id
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."
"$TODO" set "$ID" --body="...more..."                # iterate freely while groom

# later, when ready to work it:
"$TODO" init --id "$ID"                              # promote: branch + state=ready
# add --stay-on-parent to file/promote from a shared checkout without switching onto
# the new branch.
```

State meaning: `groom` = created, still collecting data, branchless;
`ready` = has a branch, ready to work (started or not).

`init --summary=...` with no existing record still works as a one-shot fresh
create (mint + branch in one call) for backward compatibility, but the two-phase
`mint` + `set` + `init` flow above is the default. `set` always takes an
explicit selector: an Id prefix or the full digest.

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

`State` is an object with **exactly one** key: the state name (a noun -- we
prefer nouns over gerunds). Optional fields live in that state's value object.
Mainline flow is `groom -> ready -> working -> done`; subtodos the parent merges
go `done -> merged`. `userneeded` and `stopped` are the interrupts a normal run
may hit.

| State | Value shape | Meaning |
|-------|-------------|---------|
| `groom` | `{}` | Minted; still collecting data / grooming. Not yet workable; branchless (store-only) until `init`. (was `pre`/`pre-init`) |
| `ready` | `{}` | Groomed and ready to work; has a branch. Not yet started. (was `init`) |
| `working` | `{ "owner"?: string, "expire"?: rfc3339 }` | Active work. (`owner`/`expire` only matter for future multi-owner handoff; omit on a single-agent run.) |
| `userneeded` | `{ "note"?: string }` | Agent blocked; needs user input. |
| `stopped` | `{ "note"?: string }` | User override halt. |
| `done` | `{ "last_commit"?: string }` | Complete on the ticket branch; record last commit message if useful. Entering `done` tears down the todo's worktree (worktree-lifecycle invariant). |
| `merged` | `{ "merged_into"?: string, "last_commit"?: string }` | Parent absorbed this branch; written on the **child** todo after merge. Parent `Subtodos[].State` becomes `merged`. Entering `merged` tears down the todo's worktree (worktree-lifecycle invariant). |
| `fact` | `{}` | An informational anchor: a todo that will **never** be worked, kept to harness vector-memory associative recall. (was `info`) See "Working a fact" below. |
| `waiting` | (deferred) | Blocked on subtodos -- see Deferred. |
| `N/a` | `{}` | Non-work associative item; not a task. |

Always patch `State` and `update_dt` together.

**Working a fact.** `fact` todos are memory anchors, not work items. Before you
start work on a `fact` todo -- `set <id> --state working`, opening a worktree, or any
code/ticket action -- STOP and ask the user to confirm they really want it
worked. Never transition a `fact` to `working` on your own.

The terminated states `done` and `merged` are the `FINAL` set, hidden by default
by `ls`/`search` (see "Selecting todos").

### Selecting todos

`ls` and `search` share one state filter. By default they hide the terminated
`FINAL` states (`done`, `merged`) so you see live work. Precedence:
`--states` > `-s` (which means `ALL`) > the per-dir default in
`<todo-dir>/config.json` (`"default_state_filter"`, default `ALL,-FINAL`).

`--states=<expr>` is a comma/`+`/`-` expression, evaluated left-to-right, over
lowercase state names and UPPERCASE macros: `ALL`, `FINAL` (done, merged),
`PAUSING` (waiting, userneeded, stopped), `WORKING` (working),
`UNSTARTED` (groom, ready), `INFO` (fact). `-s` also adds a State column.

```bash
todo ls                                 # live work (FINAL hidden)
todo ls -s                              # everything, with a State column
todo ls --states=WORKING                # only actively-worked todos
todo ls --states=UNSTARTED+PAUSING      # not-yet-started or blocked
todo ls --states=ALL,-done              # everything except done
todo ls --states=fact                   # browse the fact / memory corpus
todo search "auth token" --states=WORKING+PAUSING
todo search bh 791 -s                   # search all states, show State column
```

To change the default per todo dir, set `"default_state_filter"` in
`<todo-dir>/config.json` (e.g. `"WORKING+PAUSING"`).

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
| `ActualSummary` | string (optional) | How the work actually panned out (vs the planned `Summary`). Written at finish via `set <id> --state done --actual-summary=...`; when this todo is later merged into a parent, `merge-subtodo` reuses it as the merge commit subject and the parent's `merge_subtodo` work item summary, falling back to `Summary.raw` when absent. |
| `Tag` | list of objects (optional) | Plural, provenance-tracked tags. Each element is `{raw, manual, <embedder>: vectors}`: `raw` is the tag text (short, free-form, may contain spaces, always stored **downcased**); `manual` is `true` for a hand-set tag (`tagadd`, or the `set <id> --tag` alias), `false` for an automatic zero-shot semantic tag. Automatic tags are derived from Summary+Body -- `doctor` recomputes them (trust-existing / backfill-empty), and editing Summary or Body drops them for recompute; **manual tags are sticky** (never auto-removed). Each element's `raw` is embedded like Summary/Body, so tags rank in `search` and filter via `search --tag=a,b` (any element's `raw`, case-insensitive). Deduped; the field is dropped when empty. (Migrated from the legacy flat `Tags` string list by `RECORD_MIGRATIONS[7]`.) |

`Summary.raw` and `Body.raw` are always present; embedding keys are optional
enrichments, omitted on first write and backfilled later if ever.
`ActualSummary` and `Tag` are optional and omitted when unused.

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
`set <child-id> --state` through the normal CLI.

Initial implementation:

1. Parent records a barrier WorkItem with `execution.primitive =
   "wait-and-merge"` and `wait_for` child Ids.
2. Child runs its lifecycle loop to `is-done` and reaches `set <child-id> --state done`.
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
- **Git hooks:** too magical for v1. Avoid coupling child `set <id> --state` to
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

`todo.py doctor <selector>|ALL` audits and, by default, repairs. It re-establishes
follow-only `INFO` parent back-links from the audited todo's `Parent` refs
(best-effort, same-repo, store only); `--dry-run` makes it report-only and
selector `ALL` sweeps the whole corpus. Checks:

- Selector resolution: ids are unambiguous.
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

**Create (two phases).** "Make a todo" = `todo.py mint` (creates a `groom`
record + Id, no branch) then `todo.py set <id> --summary=... --body=...
--ac=...` to fill it in while collecting data. "Work the todo" (when the design
is ready) = `todo.py init --id <id>` (prefer `--stay-on-parent` from the main
checkout), which creates the branch, records `BaseSha` (invariant #5), and moves
it to `ready`. Then `git worktree add` the todo branch and **verify**
main-on-master + CWD-in-worktree before any code work. See **Hard rule: work
todos only in worktrees** and **Two-phase lifecycle** under **Id minting**.
(`init --summary=...` still one-shot-creates for backward compat.)
Plan the work as WorkItems with `work-item-add <id> --summary=...` -- store-only,
so the plan can be seeded while the todo is still a branchless `groom` record;
keep the **head of the list small enough to be one trackable unit** (see
`frequentcommits`).

**Poll.** Ask the tool what to do next, then act, then poll again:

```bash
todo.py work-item-read <id>   # the cursor + a `next` hint, or the finish action when done
todo.py is-done <id>          # exit 0 when nothing is left, 1 otherwise
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
| a subtodo to start | `todo.py add-subtodo <parent-id> --summary=...` | `start_subtodo` (+ child branch & `BaseSha`) |
| a subtodo to land | git-merge the child, then `todo.py merge-subtodo <child-id>` | `merge_subtodo` (+ parent branch tip sha) |
| local coding | make the change in the todo's worktree, then `todo.py work-item-done <id>` (dirty tree commits it, message = `-m` or the item summary; clean tree records HEAD) | `code` (+ HEAD sha) |
| too coarse | `todo.py work-item-insert <id> --summary=...` to split it, then re-poll | new task at the cursor |
| blocked on children | `todo.py wait-for <id>...` / `wait-and-merge <id>...`, or `set <id> --state userneeded --note=...` and **come back and poll later** | -- |
| empty (`is_done == true`) | run `todo.py doctor <id>` (must be `ok`); read the done items (`todo.py read <id> | jq '.WorkItems'`) and **synthesize a 1-3 sentence ActualSummary of what actually landed**; then `todo.py set <id> --state done --actual-summary="..."` | `done` (State) |

"Come back and ask again later" is a first-class outcome: when the next item is
a barrier, wait/poll rather than forcing progress.

**Finish (the `is_done == true` branch of the loop).** When `is-done`, the last
item is a `code` or `merge` commit (invariant #6), so `todo.py last-sha <id>` is
the branch's last commit. This is a directed sequence, not an optional coda:

1. Run `todo.py doctor <id>`; it must be `ok` before finishing.
2. Read the completed WorkItems -- `todo.py read <id> | jq '.WorkItems'` -- and
   **synthesize a 1-3 sentence ActualSummary of what actually landed**: how the
   work panned out versus the planned `Summary`, noting any pivots, descoped
   items, or surprises. This is the retrospective, not a restatement of the plan.
3. `todo.py set <id> --state done --actual-summary="<that synthesis>"`.

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

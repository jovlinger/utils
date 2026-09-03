# Todo implementation reference

status: living document - normative owner for CLI, storage, schema, migrations,
permalinks, doctor, compatibility, and planned features

Load this when you need exact command syntax, record fields, store layout, or
compatibility notes. Policy and runbooks live elsewhere:

- Intent / safety card -> [`SKILL.md`](SKILL.md)
- Ticket design / dispatch -> [`GROOMING.md`](GROOMING.md)
- Start -> finish runbook -> [`WORKING.md`](WORKING.md)

---

## Terminology (frozen)

| Term | Meaning |
|------|---------|
| **ticket** / **todo** | One task record addressed by `Id` |
| **record** | The JSON object for a ticket (sqlite or json-dir backend) |
| **resolved store** | The todo directory chosen for this invocation (`todo.py basedir`) |
| **todo branch** | Git branch named in the record's `Branch` field |
| **todo worktree** | Dedicated linked worktree checking out that branch |
| **tracked subtodo** | Child registered via `add-subtodo` (merge obligation) |
| **INFO backlink** | Follow-only `Subtodos` row (`State: "INFO"`) from `set --parent`; no merge obligation |

Do **not** teach agents that a live ticket "lives in" `TODO.json`. Current
records live in the resolved store. Legacy `TODO.json` is import-only -- see
[Compatibility](#compatibility-and-history).

---

## Document sections

1. [Current public contract](#current-public-contract) -- agents may rely on this
2. [Maintainer internals](#maintainer-internals)
3. [Compatibility and history](#compatibility-and-history)
4. [Deferred and planned](#deferred-and-planned) -- non-normative

---

# Current public contract

## Store resolution

Resolved once per `todo.py` invocation. The storage anchor is the repo's
**main checkout root** (first `git worktree list` entry), not the current
linked worktree -- every worktree of a repo shares one store.

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
| Search config | `<todo-dir>/config.json` (`search_stopwords`, `search_stopword_min_idf`, `embedder`) -- see [Search ranking](#search-ranking) |

`TODO_USE_JSON=1` enables legacy file mode (import-oriented). There is **no
`--repo` flag** -- `cd` into the target repo/worktree; CWD must be a git repo.

Print the resolved base with `todo.py basedir`. Print a todo's main-checkout
repo path with `todo.py repodir <selector>`.

### Repository-local storage

SQLite and `storage/*.json` are interchangeable backend features. They should
be opaque to an agent following the grooming or working runbook: use
`todo.py`, not the backend files.

A resolved store inside a repository checkout is supported, but versioning its
ticket data beside source changes is a **very strong anti-pattern**. Routine
ticket writes can otherwise dirty the repository and create unrelated merge
pressure. This is not forbidden: a workflow may intentionally version that
state. Prefer an external or ignored store when ticket history is not meant to
be code history.

**Desired tool behavior (not implemented by this document):** warn prominently
on every invocation when the resolved store is inside the current repository
and is not ignored. The warning should name the resolved path and explain the
intermingling risk, but must not block supported workflows.

## Selectors

| Selector | Meaning |
|----------|---------|
| `<id-prefix>` | Unambiguous 4+ hex prefix of the 64-hex `Id`, or the full digest |
| `ALL` | Whole corpus -- recognized by `doctor`, `log`, `export-to-file`, `tag-clear` |

Former `self`/`curr` current-branch aliases are **removed**. Every command that
targets a todo takes an explicit selector. Capture the Id from `mint` / `init`.

## CLI: implemented commands

Mechanism only. Policy (sizing, sequencing) lives in `frequentcommits` and
[`GROOMING.md`](GROOMING.md) / [`WORKING.md`](WORKING.md).

All ticket access goes through `todo.py`. Never `cat`/`jq`/`Read` a store file
or legacy `TODO.json` directly. Filtering after a sanctioned read is fine:
`todo.py read <id> | jq '...'`.

### Identity and listing

| Command | Behavior |
|---------|----------|
| `mint` | Mint Id + create store-only `groom` record (no git branch). Prints 64-hex Id |
| `init [--id <id>] [--summary=...]` | Promote `groom` -> branch + `ready`, or fresh one-shot create. `--stay-on-parent` returns to previous branch. Refuses second ticket on current branch |
| `ls [--states=<expr>] [-s] [-t\|-tc\|-tu\|-g]` | List short id + summary. Hides FINAL by default |
| `read <selector>` | Print ticket JSON |
| `prompt <selector>` | Ancestor Summary/Body chain (farthest first) -- startup context |
| `search <term>...` | Vector + lexical IDF search; same state/column flags as `ls`. See [Search ranking](#search-ranking) |
| `embedders` | List selectable search embedders |
| `log <selector>\|ALL` | Graph of `Subtodos` tree (`-n`, `-v`, `-t`) |
| `basedir` / `repodir <selector>` | Print todo dir / main-checkout repo path |
| `rm <todoid> [--hard]` | Soft-delete (tombstone) or hard-delete; leaves git branch/worktree |

### Field access

| Command | Behavior |
|---------|----------|
| `get <selector> --summary\|--body\|--ac\|--state\|--actual-summary\|--long-summary\|--parent\|--tag` | Exactly one flag; friendly wrapper over `get-json-path` |
| `get-json-path <selector> <path>` | Low-level path read |
| `set-json-path <selector> <path> [--file <path>]` | Low-level path write (stdin or `--file`). Store-only |
| `set <selector> [--summary=] [--body=] [--ac=] [--state=<s>] [--actual-summary=] [--long-summary=] [--parent=<id>] [--tag=] [--untag=]` | Patch fields and/or state. Store-only. Requires at least one field. `--parent` is make-it-so Parent list + INFO backlinks. `EDIT` as a value captures free text from `$VISUAL`/`$EDITOR`/`vi` (exits 1 non-interactively) |
| `tag-add` / `tag-rm` / `tag-clear` | Manual tag ops (`set --tag`/`--untag` aliases for add/rm) |
| `resolveurl <path-or-url>` | Dereference permalink; no selector (todo is first path segment) |

### Subtodos and waiting

| Command | Behavior |
|---------|----------|
| `add-subtodo <parent> (--from-json=... \| --summary=...)` | Create child at tip of parent branch (no checkout). Requires `--summary` unless `--from-json`. Optional `--body`, `--ac`, `--id`, `--branch`, `--path-from-root`. Registers tracked subtodo; completes parent cursor as `start_subtodo` |
| `merge-subtodo <child-id>` | **Store bookkeeping only** after child is `done`. Locates parent via `Parent[0]`. Records `merge_subtodo` with parent branch tip sha. **Does not run `git merge`** -- caller must already have integrated the child branch |
| `wait-for <id>...` | Poll until children reach target state (default `done`) |
| `wait-and-merge <subtodo-id>...` | Poll until `done`, then run `merge-subtodo` for each. **Does not git-merge branches** -- same bookkeeping as `merge-subtodo` |

### Work items

| Command | Behavior |
|---------|----------|
| `work-item-add <selector> --summary=...` | Append not-done `task` |
| `work-item-insert <selector> [target] --summary=...` | Insert task before `target`, pushing it down (default: the cursor). Appends only when the plan has no open item |
| `work-item-replace <selector> [target] --summary=...` | Reword a not-done task (default: the cursor). Keeps the item's `objid` |
| `work-item-delete <selector> [target]` | Delete a not-done task (default: the cursor). Erases it; prefer `work-item-obsolete` once the plan is real |
| `work-item-obsolete <selector> [target] -m MSG` | Close a not-done item as **no longer wanted** (`obsolete`), keeping it and the required reason in the trail. Moves it to the end of the done prefix (#3). Store-only; no branch checkout |
| `work-item-reorder <selector> <src> <dst>` | Move one not-done item to position `dst`. `src` is an index or `objid:`; `dst` is an index only, negative counting from the end (`-1` is last). Refuses the done prefix at both ends (#3) |
| `work-item-read <selector> [target]` | A work item + `next` mechanism hint (default: the cursor). Reads a done item too; `next` always describes the cursor |
| `work-item-done <selector> [-m MSG] [--sha SHA] [--summary S] [--checkpoint] [--blocked]` | Complete cursor as `code` (or `--checkpoint` / `--blocked`). Must run from a checkout of the todo's branch. `--blocked` requires `-m` and a clean tree; refuses `--sha` and refuses `--checkpoint` |
| `is-done <selector>` | Exit 0 when no open work items |
| `last-sha <selector>` | Sha of last work item (branch tip attribution); `None` for the no-change sentinel |

### Addressing one work item

Every work-item command names ONE item, three ways:

| Address | Means |
|---------|-------|
| omitted | the **cursor** -- the first not-done item; the working default |
| `<int>` | a 0-based index into `WorkItems`; negative counts from the end the way python indexing does, so `-1` is the last item |
| `objid:<hex>` | the item carrying that `objid`. An objid is an allocation number rendered `%04x`, so leading zeros are optional: `objid:3` == `objid:03` == `objid:0003` |

A bare value is **always** an index -- `12` means index 12, not `objid:0012` --
which is the permalink grammar's rule restated, and why an id has to name its
scheme. The 4-character floor permalinks put on a prefix does **not** apply
here: this prefix is matched against one short list, not the whole record, so it
is padded to a whole id first and is then either unique or reported ambiguous.

Only the not-done frontier is editable (#3). `insert` / `replace` / `delete` /
`reorder` / `obsolete` refuse a done target; `read` will read one, because
reading is not editing.

An index is convenient and perishable: every insert, delete, and reorder
renumbers the items after it. An `objid` survives all three -- and rewording and
completion -- so a plan edit worked out in advance addresses by objid rather
than by indexes that were read before the first move:

```bash
# push two stalled steps to the end, in that order, without recomputing indexes
todo.py work-item-reorder <id> objid:0007 -1
todo.py work-item-reorder <id> objid:000a -1
```

`work-item-reorder` moves ONE item and leaves the relative order of the rest
alone, which is what makes a topological pass over a mis-ordered plan cheap:
send each item to `-1` in the order you want them run, first to last, and after
the final move the plan reads in exactly that order. It is **not** a substitute
for `work-item-done --blocked`: reorder is for a step that is fine but mistimed,
`--blocked` is for one that cannot be done as written.

### Maintenance and I/O

| Command | Behavior |
|---------|----------|
| `doctor <selector>\|ALL [--dry-run]` | Audit + repair (INFO backlinks, schema sweep, PR reconcile via `gh`) |
| `migrate-to-latest [--dry-run]` | Explicit record sweep to `SCHEMA_VERSION` |
| `clear-search-data <selector>\|ALL` | Drop derived search data: embedding vectors (index + stamped JSON) and, on `ALL`, the discovered stopword list. Re-derived lazily by the next `search`. See [Search ranking](#search-ranking) |
| `import-json --from-json PATH \| --scan-refs` | Import legacy JSON into the store |
| `export-to-file <ids...>\|ALL [--remove[{=soft\|hard}]]` | Export round-trippable JSON under `<basedir>/storage/` |
| `web [selector] [--host] [--port] [--dump-html]` | Serve viewer + permalinks (default bind `localhost:8765`) |

### STUB (not automation)

| Command | Status | Behavior today |
|---------|--------|----------------|
| `ensure_worktree <todoid> [--init] [--no-commit]` | live | With `--init`, promotes a groom todo when its git branch is missing (same as `init --id … --stay-on-parent`; noop when the branch exists). Then creates or reuses a linked worktree via `git worktree add`. Without `--init`, exit 1 when the branch does not exist yet. Prints `inited`, `created`, and `worktree` |

Worktree removal remains manual on finish (see [`WORKING.md`](WORKING.md#6-finish-and-remove-the-worktree)).
Do not assume a worktree exists until `ensure_worktree` succeeds.

### Minimal examples (verified forms)

```bash
TODO=skills/projectmanagement/todos/todo.py

# make (no branch)
ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."

# promote when ready to work
"$TODO" init --id "$ID" --stay-on-parent

# subtodo -- either seed form
"$TODO" add-subtodo "$ID" --summary="Child research domain"
# or: "$TODO" add-subtodo "$ID" --from-json=./child-seed.json

# integrate child code, THEN bookkeeping
git merge "<child-branch>"   # on parent branch, in parent worktree
"$TODO" merge-subtodo <child-id>
# or after git merges: "$TODO" wait-and-merge <child-id>...
```

## State machine

`State` is an object with **exactly one** key. Mainline: `groom -> ready ->
working -> done`. Subtodos the parent absorbs: `done -> merged`. Interrupts:
`userneeded`, `stopped`.

| State | Value shape | Meaning |
|-------|-------------|---------|
| `groom` | `{}` | Minted; collecting data; branchless until `init` |
| `ready` | `{}` | Has a branch; not yet started |
| `working` | `{ "owner"?: string }` | Active (`expire` reserved, not settable) |
| `userneeded` | `{ "note"?: string }` | Blocked on user. The `note` is the SHORT form -- which item, what decision is asked for -- pointing at the work item that carries the detail (see [`WORKING.md`](WORKING.md#5-handle-userneeded-or-stopped)) |
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

**PR handoff (root todos only):** `done` -> `set <id> --state merged --pr <N>`.
`doctor` reconciles merge_commit / `rejected` via `gh`. Subtodos with `Parent`
are skipped for PR reconcile.

**Working a `fact`:** before any `working` transition or worktree, stop and ask
the user. Never self-start a `fact`.

### State filters (`ls` / `search`)

Precedence: `--states` > `-s` (means `ALL`) > config `default_state_filter`
(default `ALL,-FINAL`).

Macros: `ALL`, `FINAL`, `PAUSING` (waiting, userneeded, stopped), `WORKING`,
`UNSTARTED` (groom, ready), `INFO` (fact).

### Search ranking

`search` fuses (reciprocal rank) one ranking per selected embedder with **one**
lexical ranking over all text terms. The lexical half is IDF-weighted full-text, in
`todo_search.py`:

**Query syntax**

| Piece | Behavior |
|-------|----------|
| Text terms | Space-separated (each CLI argv is one term; the web box uses `shlex`). **OR**, google-style: each term is its own matcher; a doc matching only one term can appear; matching more terms ranks higher. Quote a phrase to keep it one term |
| Time operators | `tc_before:`, `tc_after:`, `tu_before:`, `tu_after:` each glued to an RFC3339 `Z` timestamp or a date-only `YYYY-MM-DD` / `YYYY/MM/DD` (no space). Filter `create_dt` / `update_dt` inclusively. Date-only *after* starts at 00:00:00Z that day; date-only *before* ends at 23:59:59Z. **AND** with each other and with text terms. Operator-only queries list matches sorted by `update_dt` desc. Matches excluded by the default state filter are counted on stderr as ``... N hidden by status`` |

| Piece | Behavior |
|-------|----------|
| Tokenizer | Runs of letters/digits, downcased, then stemmed. Digits are kept -- ids and ticket keys are what people type |
| Stemming | `STEMMER` is a **seam**: rebind the module attribute to drop in Porter/Snowball without touching a caller. Shipped `stem()` is crude and idempotent -- de-pluralize (`-es` only after a sibilant; never after `ss`), de-gerund (`-ing`, refused when the stem would be under 4 chars), then drop a trailing `e` on words of 5+ so `merge` and `merging` agree |
| Scoring | Each document scores the IDF of every distinct query token it holds; a rare term dominates a corpus-wide one. Weights are floored so a term in EVERY todo still returns its todos. A document matching nothing is absent, not scored zero |
| Phrases | A multi-token term (a quoted phrase) earns a bonus where its tokens appear contiguously -- IDF alone cannot see word order |
| Stopwords | Discovered, never shipped: a term whose IDF falls below `search_stopword_min_idf` is skipped. Matching ONLY a stopword is not matching. Skipping is suspended when the WHOLE query is stopwords, so searching common words still returns their todos |

**Nothing lexical is persisted.** The corpus is tokenized fresh per search
(milliseconds for a few hundred records); embedding is expensive and earns
storage, tokenizing does not. The one durable lexical artifact is the discovered
stopword list.

Config keys, per todo dir in `config.json`:

| Key | Meaning |
|-----|---------|
| `search_stopwords` | The discovered list. Written on the first search that finds one, then reused verbatim -- so a hand-edited list is honored. Derived data: `clear-search-data ALL` drops it and the next search rediscovers it against the corpus as it stands then (which is how a list that has gone stale gets corrected) |
| `search_stopword_min_idf` | Cut-off for discovery (default `0.3`, i.e. a term in roughly 74%+ of todos) |
| `embedder` | Absent or **`null` = none** (default): lexical IDF and id-prefix search only; nothing instantiates an embedder, so no NLCE sidecar spawns and no vector is backfilled. A string (comma list) or list re-enables vector search. `--embedder` always overrides; any other value type errors |

`--dry-run` discovers stopwords for that run but persists nothing, matching how
it already refuses to backfill vectors.

## Record schema

Allowed top-level fields (unknown keys -> doctor findings):
`AC`, `ActualSummary`, `Agent`, `BaseSha`, `Body`, `Branch`, `Id`, `LongSummary`,
`Parent`, `Scope`, `State`, `Subtodos`, `Summary`, `Tag`, `Tags` (legacy),
`WorkItems`, `create_dt`, `update_dt`, `_schema`, `_nextobjid`.

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
them; doctor hard-fails missing/malformed/duplicate ids. Immutable means through
edits too: a work item keeps its id when reworded, moved, or completed. Ids are
allocation numbers rendered `%04x`, which is why the CLI accepts a short
spelling (`objid:3`) where a permalink insists on 4+ characters -- see
[Addressing one work item](#addressing-one-work-item).

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
| `LongSummary` | optional `{ "raw": "<reader-first summary of Body>" }`; DERIVED from `Body` but not tool-coupled to it (below). Set with `set <id> --long-summary=` |
| `AC` | string |
| `ActualSummary` | optional string at finish; reused by `merge-subtodo` |
| `Tag` | optional list of `{raw, manual, ...}`; manual sticky; auto-tagging dormant |

`Summary.raw` and `Body.raw` are always present. `ActualSummary`, `LongSummary`
and `Tag` are optional and omitted when unused.

### LongSummary: the field contract

A careful summary of the `Body`. **Exactly two things may read it:** display to a
user, and generating the summary embedding. That list is exhaustive -- in
particular it does **not** feed `prompt`, whose output goes to an agent, not a
user. How to write one:
[`GROOMING.md`](GROOMING.md#writing-a-longsummary).

Why it exists: `Body` is usually too long for an embedder to handle well, so the
signal gets diluted or truncated and the vector matches poorly. `Summary`, `Body`
and `LongSummary` are all embedded additively; `LongSummary` is written as a
single coherent unit and so is expected to yield ONE phrase vector where `Body`
produces a list of n-phrase vectors. It is DERIVED in the same spirit as an
embedding: nothing is lost if it is regenerated from scratch.

**There is no tool connection to `Body`.** Zero access control beyond agents
obeying this skill, and no tool-level coupling:

- Editing `Body` does not clear, drop, regenerate, or flag `LongSummary`.
- Editing `LongSummary` clears only its own vectors, like any raw field.
- `doctor` checks its SHAPE only. It will never report a `LongSummary` as
  missing, stale, or inconsistent with its `Body` -- the tool cannot judge that,
  and the absence of the check is deliberate, not an oversight.

Setting one without the other is therefore **completely allowed**; the motivating
case is a HICAP agent rewriting a `LongSummary` a MIDCAP agent wrote, touching
nothing else. The consequence is that **staleness is on you**: materially change
a `Body` while a `LongSummary` exists and you rewrite it in the same breath,
because nothing else will notice.

### WorkItems and invariants

| kind | fields | produced by |
|------|--------|-------------|
| `task` | `summary`, `done:false` | `work-item-add` / `work-item-insert` |
| `code` | `summary`, `sha`, `message`, `done:true` | `work-item-done`; also `work-item-done --blocked` for an item that cannot be done as written (`sha` = the no-change sentinel, `-m` required) |
| `merge_subtodo` | `summary`, `subtodo_id`, `sha`, `done:true` | `merge-subtodo` |
| `start_subtodo` | `summary`, `subtodo_id`, `done:true` | `add-subtodo` |
| `checkpoint` | `summary`, `at_sha`, `message`, `done:true` | `work-item-done --checkpoint` |
| `obsolete` | `summary`, `message`, `done:true` (no `sha`, no `at_sha`) | `work-item-obsolete` |

Cursor = first not-done item (derived). The not-done tail is the plan's
**frontier** and the only editable part of it: `work-item-insert` /
`-replace` / `-delete` / `-reorder` all work there and refuse a done target,
which is #3 holding rather than four separate rules. An item's `objid` is its
identity through all of it -- rewording, moving, and completing keep it, so a
permalink minted while a step was still open resolves to the finished step.

**`sha` vs `at_sha` (attribution vs observation).** A `code`/`merge_subtodo`
`sha` means "this commit IS this item's work". A `checkpoint` records `at_sha`
instead: where branch HEAD stood when a no-commit step finished, claiming no
authorship. `message` on a `code` item is the full commit message recorded at
`sha`, which makes the trail self-describing -- so `-m` must state the concrete
outcome (files/tests added, with paths), not a vague label. Inapplicable flags
raise rather than being silently dropped (`-m` on a clean tree without
`--checkpoint`/`--blocked` errors; `--sha` with either errors).

**Done means CLOSED, not accomplished.** Three commands end a step and they
claim different things. `work-item-done` COMPLETED it. `work-item-done
--blocked` still OWES it: it cannot be done as written, so someone has to
decide what happens next. `work-item-obsolete` owes it NOTHING -- the step is
no longer wanted (descoped, superseded, subsumed), and `-m` says which. All
three are `done` for the cursor, `is-done`, and #3, because every reader of the
plan is asking "is this still open?".

`work-item-obsolete` is also the reason `work-item-delete` should be rare: once
a plan is being worked, deleting a step erases the fact that it was ever planned
along with the reason it was dropped, while an obsolete item keeps both where a
later reader will walk them. Delete is for a plan that was never right (still
`groom`); obsolete is for one that changed. Because the item is patched rather
than rebuilt, it keeps its `objid` and any permalink to it stays valid.

**The no-change sentinel (`sha` = 40 zeros, `WORKITEM_NULL_SHA`).** A done
`code`/`merge` node may carry git's null object id to say "no commit"
explicitly. Two producers:

- `work-item-done --blocked -m "<long form>"` -- the item CANNOT be done as
  written. Where a checkpoint says "no commit, step finished", the sentinel says
  "no commit, and none is coming". Procedure:
  [`WORKING.md`](WORKING.md#5-handle-userneeded-or-stopped).
- The legacy retrofit for old records that misattribute a foreign commit,
  without converting the node's kind.

`doctor` accepts the sentinel mid-list, never tries to resolve it, and rejects it
as the last item of a done todo (invariant #6, same as `checkpoint`); `last-sha`
reports `None` for it, never the zeros. That last rule is load-bearing for a
blocked item: it is the tool refusing to call a todo finished when its final act
was failing to do something.

**Invariants** (tool + `doctor`; numbers kept stable):

1. A done item is `start_subtodo`, `checkpoint` (observational `at_sha`, never
   attributing `sha`), `obsolete` (a `message`, and neither kind of sha), or a
   `code`/`merge_subtodo` that carries a `sha` plus a high-level description.
2. A not-done item is freetext (`task`) -- a step or a prose list of not-yet-
   started subtasks -- with `done:false`.
3. Done items form a prefix; the cursor moves monotonically down (list may grow).
4. One todo <-> one branch; the ticket's lifetime matches that branch's role as
   the durable code line for the work (worktrees are ephemeral).
5. `BaseSha` records the branch's initial sha, captured at branch creation
   (`init` / `add-subtodo`).
6. The last item of a done todo cannot be `start_subtodo`, `checkpoint`, or
   `obsolete` (or the null-sha sentinel); it must be a real `code`/`merge`
   commit so `last-sha` is the branch tip.
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
| `/<todoid>/workitem/idx/5/summary` | the same, written out; `idx` is the default key |
| `/<todoid>/workitem/sha/883368/summary` | where-clause on `sha` (4+ prefix) |
| `/<todoid>/subtodo/subtodo_id/13e5` | where-clause on `subtodo_id` (4+ prefix) |
| `/<todoid>/objid/0a3f` | canonical object link |

Indexes are 0-based, matching the json dot-path, `jq`, and `doctor` finding
labels. A bare segment is **always** an index -- there is no bare-hex fallback,
so a hex value must name its key (`sha/883368`). Only `sha`, `subtodo_id`, and
`objid` take 4+ character prefixes (ambiguity is an error); an index is exact.
A list-valued field whose name ends in `s` also answers to the name minus that
`s` (naming the element type: `WorkItems` answers to `workitem`), with an exact
match winning over the alias. Prefer objid over indexes when linking durable
content -- `work-item-insert`, `-delete`, and `-reorder` all shift later items,
so `/workitem/1` silently comes to mean a different item, while an objid keeps
naming the same one ([addressing](#addressing-one-work-item)).

`todo.py web` serves a permalink **in place**: `GET /<todoid>/<path...>` renders
the whole todo, scrolled to and focused on the resolved object. No redirect --
the path IS the resource. Resolution is entirely server-side, which is why the
grammar can use prefixes. Degrading is deliberate rather than fatal:

| The path resolves to | You get |
|----------------------|---------|
| a work item, subtodo, or parent | the page, that box focused and scrolled to |
| a scalar inside one | the page, focused on the box that holds it |
| an object the viewer does not draw | the page, focused on the nearest thing it does draw |
| a section (`Summary`, `Scope`, `Tag.0`) | the page, that section scrolled to and marked |
| the `State` subtree, or `/<todoid>` alone | the page, unfocused |
| nothing | 404 |

**A large section arrives collapsed, and focus opens it.** A section whose
content is oversized (a long `Body`, a `WorkItems` list past a handful of items,
a long state `note`) renders shut as a header carrying a size hint (`Body 88
lines`, `Work items 19 items`), and an oversized box summary is height-clamped
behind a `...more` expander. Under the thresholds nothing collapses. Collapsing
never hides a permalink's own target: a section CONTAINING the resolved object
renders **open**, decided server-side, so every row of the table above still
describes what you land on. Focus only ever opens -- it does not close a section
you expanded, does not touch siblings, and re-rendering the same permalink gives
the same page.

Clicking a box rewrites the address bar to `/<todoid>/objid/<objid>`
(`replaceState`), so whatever is on screen is already a copyable permalink.

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

Notable record transforms (historical -- see Compatibility):

- v6: `Chunks`->`WorkItems`, `Subtickets`->`Subtodos`, Parent dict->list, strip
  `Scope.path_to_project`
- v7: flat `Tags` -> plural `Tag` elements
- v8: state renames `pre`/`pre-init`->`groom`, `init`->`ready`, `info`->`fact`

## Startup health

- Store behind -> interactive warning to run `todo.py doctor ALL`
- Agent-framework detection -> skills-buried warning on stderr (once per session)

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

# Compatibility and history

**Legacy `TODO.json`:** import-only via `import-json --from-json` or
`--scan-refs`. Do not infer ticket presence from a worktree file. Doctor may
warn about leftover files. `TODO_USE_JSON=1` is legacy file mode.

**Renamed states:** `pre` / `pre-init` -> `groom`; `init` -> `ready`; `info` ->
`fact`. Do not use old names in current examples.

**Removed selectors:** `self` / `curr`.

**`set-state` subcommand:** removed; use `set --state`.

---

# Deferred and planned

Non-normative. Do **not** put these in current dispatch tables.

| Item | Notes |
|------|-------|
| `todo.py new` | Mentioned historically as alias for `init` with JSON seed -- **not implemented** |
| `ensure_worktree` automation | `--init` promotes groom branch when missing; then `git worktree add` under `<todo-dir>/worktrees/...` |
| `waiting` state / dependency graph | In `VALID_STATES` / macros but not settable via `--state`; design deferred |
| `N/a` state | Present but not settable via `--note`/`--state` workflow |
| Stack across branches | Deferred |
| `working` lock / `expire` semantics | Reserved |
| Embeddings format canonicalization | Ongoing / deferred |
| Worktree add/list/remove CLI family | Future if parallel-checkout needs it |

Related skills: `frequentcommits` (WorkItem sizing policy),
`bookmark-management`, `project-lifecycle` (separate `TODOs.md` format -- do not
merge without user direction).

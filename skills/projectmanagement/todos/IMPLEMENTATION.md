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

The winning directory's own `config.json` may then redirect to a different
directory via `todo_dir` -- see [Redirecting to another directory](#redirecting-to-another-directory)
-- and the redirect target, not the originally selected directory, is what
gets used for everything below.

| Item | Location |
|------|----------|
| Tickets | `<todo-dir>/sqlite.db` or `<todo-dir>/storage/*.json` |
| Worktrees (convention) | `<todo-dir>/worktrees/<repo-path>/<branch>` |
| Embeddings | In ticket JSON; sqlite also mirrors a derived index |
| Search config | `<todo-dir>/config.json` (`search_stopwords`, `search_stopword_min_idf`, `embedder`) -- see [Search ranking](#search-ranking) |
| File-store git sync | `<todo-dir>/config.json` (`autocommit`, `autopush`) -- see [File-store autocommit and autopush](#file-store-autocommit-and-autopush). Ignored for sqlite |
| Redirect | `<todo-dir>/config.json` (`todo_dir`) -- see [Redirecting to another directory](#redirecting-to-another-directory) |

### Redirecting to another directory

A resolved candidate's `config.json` may carry a `todo_dir` key: a path to a
different directory, which becomes the actual todo dir for the rest of the
invocation (storage, locks, worktrees -- everything keyed off the resolved
todo dir). A relative value is anchored on the redirecting `config.json`'s own
directory, not CWD; an absolute value is used as-is; `~` and `$VAR` expand the
same way other config path values do.

```json
{"todo_dir": "../../dottodo"}
```

The target's own `config.json` may itself carry a `todo_dir`, chaining the
redirect further. A chain that revisits a directory already seen -- directly
(`A` redirects to itself) or through intermediate hops (`A` -> `B` -> `A`) --
raises `CircularTodoRedirectError` immediately; it never loops and never
silently falls back to an earlier directory in the chain.

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

### File-store autocommit and autopush

Two `config.json` lists, honored only by the file backend (`file://`). Sqlite
ignores both. Each entry is a subcommand **class** name, not the CLI spelling:
`SetCommand`, not `set`. Matching is case-insensitive, and naming a non-leaf
class selects that class and every subclass (`TodoFieldCommand` covers `set`,
`read`, `rm`, and the other field commands; `WorkItemCommand` covers the whole
work-item group).

| Key | After a successful command |
|-----|----------------------------|
| `autocommit` | `git add` and `git commit` only the store files that command wrote (the ticket `.json`, a `.deleted` tombstone, `.data_version`). Other dirty files in the store repo stay unstaged |
| `autopush` | `git push` the store repo (its configured upstream) |

A read that matches through a parent class still does nothing: it wrote no
file, so there is nothing to commit or push. A command listed in `autopush`
but not `autocommit` pushes existing commits and leaves the new write
uncommitted. Both run only when the command exits 0. The git repository is the
one that contains the storage directory -- the todo dir when that dir is itself
a repo -- not the project checkout the command was invoked from.

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
| `prompt <selector>` | Ancestor Summary/Body chain (farthest first), plus the notes each Body reaches -- startup context |
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
| `set <selector> [--summary=] [--body=] [--ac=] [--state=<s>] [--actual-summary=] [--long-summary=] [--parent=<id>] [--tag=] [--untag=]` | Patch fields and/or state. Store-only. Requires at least one field. `--parent` is make-it-so Parent list + INFO backlinks. Every value is stored as given |
| `edit <selector> <target> [--no-commit]` | Opens `$VISUAL` (else `$EDITOR`, else `vi`) on a temp file holding an HTML comment header (todo id, target, and that leading comments are stripped), a blank line, then the target's current text. Stores the result with leading HTML comments and blank lines removed (a later `<!-- -->` is kept as markdown), whitespace-trimmed. A file saved untouched writes nothing; a value that itself begins with `<!--` loses that comment on a real edit. `<target>` is a dot path in the `get-json-path` grammar naming a string, or an object whose `raw` is a string (`Summary`, `Body`, `LongSummary`, `Notes.0`: edited at `raw`); or `objid:<hex>` (leading zeros optional) naming a note (its `raw`; `objid` and `relto` kept) or a work item, done or not (its `summary`; `objid` and status kept). Unchanged text writes nothing. An empty result stores the empty string (like `set --body=`), except on a note, where it deletes the note through `note-delete`'s own path (same relto handling, last note drops `Notes`, same commit message and printed JSON). Exits 1 with nothing written when stdin/stdout is not a terminal, the target is not free text, a leading `<!--` is never closed, or the editor fails. Store-only |
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
| `work-item-obsolete <selector> [target] -m MSG [--summary S]` | Close a not-done item as **no longer wanted**, as `obsolete`. `-m` required. Store-only |
| `work-item-reorder <selector> <src> <dst>` | Move one not-done item to position `dst`. `src` is an index or `objid:`; `dst` is an index only, negative counting from the end (`-1` is last). Refuses the done prefix at both ends (#3) |
| `work-item-read <selector> [target]` | A work item + `next` mechanism hint (default: the cursor). Reads a done item too; `next` always describes the cursor |
| `work-item-done <selector> [-m MSG] [--sha SHA] [--summary S]` | Complete the cursor as `code`: records a real commit, making it first (`git add -A`) when the tree is dirty. Must run from a checkout of the todo's branch. Does ONE thing -- the no-commit dispositions are the three commands below |
| `work-item-checkpoint <selector> [target] [-m MSG] [--summary S]` | Close a not-done item that FINISHED without a commit, as `checkpoint` + observational `at_sha`. Needs the todo's branch checked out (it reads HEAD) and a clean tree. `-m` defaults to an explicit no-op marker |
| `work-item-blocked <selector> [target] -m MSG [--summary S]` | Close a not-done item that is still OWED but cannot be done as written, as `blocked`. `-m` required (the long form). Store-only: no branch checkout, no clean tree |
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
`reorder` and the three closing commands (`checkpoint` / `blocked` /
`obsolete`) all refuse a done target; `read` will read one, because reading is
not editing.

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
for `work-item-blocked`: reorder is for a step that is fine but mistimed,
`work-item-blocked` is for one that cannot be done as written.

### Note and relto commands

| Command | Behavior |
|---------|----------|
| `note-add <selector> --raw=... [--relto=TARGET[:TYPE]]` | Append a note; prints the new objid. `--relto` (repeatable) adds a cross-reference; `mention` refused here |
| `note-read <selector> [target]` | One note (index or `objid:<hex>`), or every note when target is omitted. No cursor default |
| `note-replace <selector> <target> --raw=...` | Overwrite a note's `raw` in place. Keeps `objid` and `relto` |
| `note-delete <selector> <target>` | Delete a note. Drops `Notes` entirely when it was the last one |
| `relto-add <selector> <host> --target=... [--type=TYPE]` | Append a cross-reference to HOST's relto list. `--type` defaults to `relates`; `mention` refused here |
| `relto-remove <selector> <host> --target=...` | Remove a cross-reference, matched by exact target. Refuses to remove a `mention` -- edit the node's prose instead |
| `relto-read <selector> [host]` | HOST's relto list, or every relation in the record when host is omitted (each entry then carries its host path and objid) |

`target` addresses a note the same way [work items are
addressed](#addressing-one-work-item): a 0-based index (negative counts from
the end) or `objid:<hex>` (leading zeros optional); there is no cursor
default. `host` spellings: [Notes and relto](#notes-and-relto).

### Maintenance and I/O

| Command | Behavior |
|---------|----------|
| `doctor <selector>\|ALL [--dry-run]` | Audit + repair (INFO backlinks, relto mention sync, schema sweep, PR reconcile via `gh`) |
| `migrate-to-latest [--dry-run]` | Explicit record sweep to `SCHEMA_VERSION` |
| `clear-search-data <selector>\|ALL` | Drop derived search data: embedding vectors (index + stamped JSON) and, on `ALL`, the discovered stopword list. Re-derived lazily by the next `search`. See [Search ranking](#search-ranking) |
| `import-json --from-json PATH \| --scan-refs` | Import legacy JSON into the store |
| `export-to-file <ids...>\|ALL [--remove[{=soft\|hard}]]` | Export round-trippable JSON under `<basedir>/storage/` |
| `web [selector] [--loopback L] [--public P] [--host] [--port] [--dump-html]` | Serve viewer + permalinks on port 8765. `--loopback` (default `read`) and `--public` (default `none`) each take `none`, `read` or `write` for loopback and for all other clients; both `none` refuses to start. Binds `localhost` when public is `none`, else `::` (every interface, IPv4 and IPv6); `--host` overrides. Every option defaults from the `web` object of `config.json`. See [Web access and edits](#web-access-and-edits-web) |

### STUB (not automation)

| Command | Status | Behavior today |
|---------|--------|----------------|
| `ensure_worktree <todoid> [--init] [--no-commit]` | live | With `--init`, promotes a groom todo when its git branch is missing (same as `init --id ... --stay-on-parent`; noop when the branch exists). Then creates or reuses a linked worktree via `git worktree add`. Without `--init`, exit 1 when the branch does not exist yet. Prints `inited`, `created`, and `worktree` |

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
`Notes`, `Parent`, `Scope`, `State`, `Subtodos`, `Summary`, `Tag`, `Tags` (legacy),
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
| `Notes` | optional list of `{objid, raw, relto?}`; status-free facts and findings -- see [Notes and relto](#notes-and-relto) |

`Summary.raw` and `Body.raw` are always present. `ActualSummary`, `LongSummary`,
`Tag` and `Notes` are optional and omitted when unused.

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

### Notes and relto

A `Notes` element holds exactly `objid`, `raw`, and optional `relto` -- no
`kind`, no `done`, no status of any sort:

    { "objid": "<hex>", "raw": "<the fact or finding>", "relto": [...] }

A `relto` element holds exactly `objid`, `type`, and `target`:

    { "objid": "<hex>", "type": "<relation type>", "target": "<qualified target>" }

`relto` is **not** a top-level field -- `ALLOWED_TOP_LEVEL_FIELDS` does not
contain it. It is nested, and legal only on three node kinds: `Body`, a
`Notes` element, or a `WorkItems` element.

Target grammar, always namespace-qualified, every hex component 4+ characters
(the permalink floor, not the CLI's zero-padding shortcut on work items):

| Form | Means |
|------|-------|
| `objid:<hex>` | an object in THIS record -- any object, not only a note |
| `todo:<hex>` | a whole todo |
| `todo:<hex>/objid:<hex>` | an object in another todo's record |

A target is stored as written and resolved at use time, exactly like every
other selector the tool takes; a prefix that later goes ambiguous is a doctor
finding, not a silent mismatch. Prose that SHOWS the grammar writes the
placeholder spelling above -- a well-formed target in prose is a citation, and
doctor derives a `mention` from it, so an illustrative example spelled as a
real target would derive a relation to an object that was never meant to
exist.

Relation types: `mention` (derived, doctor-owned; refused from the CLI) and
`relates` (the manual default, and the only one a caller writes). An unknown
type is an error, never a silent pass-through.

Host spellings, shared by `relto-add`, `relto-remove`, and `relto-read`:

| Host | Means |
|------|-------|
| `body` | the `Body` field's own `relto` list |
| `objid:<hex>` | any object in the record (4+ hex, record-wide), checked against the three legal hosts |
| `note:<index>` | the `Notes` element at that 0-based index (negative counts from the end) |
| `workitem:<index>` | the `WorkItems` element at that 0-based index (negative counts from the end) |

Command syntax: [Note and relto commands](#note-and-relto-commands). Doctor's
`mention` sync: [Doctor checks](#doctor-checks-summary). What `Body.relto`
publishes to `prompt`, and what stays Body vs Note vs WorkItem vs subtodo:
[`BODY.md`](BODY.md).

### WorkItems and invariants

| kind | fields | produced by |
|------|--------|-------------|
| `task` | `summary`, `done:false` | `work-item-add` / `work-item-insert` |
| `code` | `summary`, `sha`, `message`, `done:true` | `work-item-done` |
| `merge_subtodo` | `summary`, `subtodo_id`, `sha`, `done:true` | `merge-subtodo` |
| `start_subtodo` | `summary`, `subtodo_id`, `done:true` | `add-subtodo` |
| `checkpoint` | `summary`, `at_sha`, `message`, `done:true` | `work-item-checkpoint` |
| `blocked` | `summary`, `message`, `done:true` (no `sha`, no `at_sha`) | `work-item-blocked` |
| `obsolete` | `summary`, `message`, `done:true` (no `sha`, no `at_sha`) | `work-item-obsolete` |

**One command per kind, always.** A `kind` is not a status a caller sets, it
is the receipt of an action: the command does the work and writes down what it
witnessed. That is why there is no `--status` -- it would let a caller assert
`code` (this step produced commit X) without producing anything, and the five
other kinds have incompatible preconditions anyway (needs the branch checked
out / needs a clean tree / needs your git merge to have happened / needs
nothing). `set --state` is the opposite case and rightly IS a setter: a todo's
State is a disposition with no artifact. The escape hatch for writing a node by
hand stays `set-json-path`, with `doctor` validating the result.

The three no-commit kinds (`checkpoint`, `blocked`, `obsolete`) share ONE
mechanism -- patch the node, then slot it at the end of the done prefix -- so
the three names buy meaning, not machinery.

Cursor = first not-done item (derived). The not-done tail is the plan's
**frontier** and the only editable part of it: `work-item-insert` /
`-replace` / `-delete` / `-reorder` all work there and refuse a done target,
which is #3 holding rather than five separate rules. An item's `objid` is its
identity through all of it -- rewording, moving, and completing keep it, so a
permalink minted while a step was still open resolves to the finished step.

**`sha` vs `at_sha` (attribution vs observation).** A `code`/`merge_subtodo`
`sha` means "this commit IS this item's work", and is always a commit on the
todo's own branch -- `work-item-done` accepts only HEAD, `merge_subtodo` records
the parent tip after your git integration. There is no field for a foreign sha:
work that originated elsewhere is landed on the branch first and its origin
recorded in the item's text
([`WORKING.md`](WORKING.md#landing-foreign-work-no-merge-node)). A `checkpoint`
records `at_sha` instead: where branch HEAD stood when a no-commit step
finished, claiming no authorship. `message` on a `code` item is the full commit
message recorded at `sha`, which makes the trail self-describing -- so `-m` must
state the concrete outcome (files/tests added, with paths), not a vague label.
Inapplicable flags raise rather than being silently dropped (`-m` on a clean
tree without `work-item-checkpoint` errors; `--sha` on a dirty tree errors).

**Done means CLOSED, not accomplished.** Four commands end a step and they
claim different things:

| Command | The claim | Needs git? |
|---|---|---|
| `work-item-done` | COMPLETED it, and here is the commit | yes: the branch, and it commits a dirty tree itself |
| `work-item-checkpoint` | FINISHED it, but it produced no commit | yes: reads HEAD as `at_sha`, clean tree |
| `work-item-blocked` | still OWED: cannot be done as written, so someone has to decide what happens next | no |
| `work-item-obsolete` | owes NOTHING: no longer wanted (descoped, superseded, subsumed) | no |

All four are `done` for the cursor, `is-done`, and #3, because every reader of
the plan is only asking "is this still open?".

`work-item-obsolete` is also the reason `work-item-delete` should be rare: once
a plan is being worked, deleting a step erases the fact that it was ever planned
along with the reason it was dropped, while an obsolete item keeps both where a
later reader will walk them. Delete is for a plan that was never right (still
`groom`); obsolete is for one that changed. Because the item is patched rather
than rebuilt, it keeps its `objid` and any permalink to it stays valid.

**The no-change sentinel (`sha` = 40 zeros, `WORKITEM_NULL_SHA`).** A done
`code`/`merge` node may carry git's null object id to say "no commit"
explicitly. Two producers:

- Old blocked items, written before `kind=blocked` existed. That spelling made
  `kind` say `code` for something that was not code, so every reader needed a
  special case; `work-item-blocked` now says it in the field that is supposed
  to. Procedure: [`WORKING.md`](WORKING.md#5-handle-userneeded-or-stopped).
- The legacy retrofit for old records that misattribute a foreign commit,
  without converting the node's kind.

Neither is migrated to `kind=blocked`: after the fact the two are
indistinguishable, and guessing would relabel a bad attribution as a decision
nobody made. Readers keep accepting the sentinel; nothing writes it any more.

`doctor` accepts the sentinel mid-list, never tries to resolve it, and rejects it
as the last item of a done todo (invariant #6, same as every no-commit kind);
`last-sha` reports `None` for it, never the zeros. That last rule is
load-bearing for a blocked item: it is the tool refusing to call a todo finished
when its final act was failing to do something.

**Invariants** (tool + `doctor`; numbers kept stable):

1. A done item is `start_subtodo`, `checkpoint` (observational `at_sha`, never
   attributing `sha`), `blocked` or `obsolete` (a `message`, and neither kind of
   sha), or a `code`/`merge_subtodo` that carries a `sha` plus a high-level
   description.
2. A not-done item is freetext (`task`) -- a step or a prose list of not-yet-
   started subtasks -- with `done:false`.
3. Done items form a prefix; the cursor moves monotonically down (list may grow).
4. One todo <-> one branch; the ticket's lifetime matches that branch's role as
   the durable code line for the work (worktrees are ephemeral).
5. `BaseSha` records the branch's initial sha, captured at branch creation
   (`init` / `add-subtodo`).
6. The last item of a done todo cannot be `start_subtodo` or any no-commit
   kind -- `checkpoint`, `blocked`, `obsolete` (or the legacy null-sha
   sentinel); it must be a real `code`/`merge` commit so `last-sha` is the
   branch tip.
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
| `/<todoid>/note/0/raw` | 0-based index into `Notes` (drop-the-s alias) |
| `/<todoid>/objid/0a3f` | canonical object link |

A note needed no grammar change: `/<todoid>/note/0/raw` resolves via the
existing drop-the-s alias (`Notes` -> `note`), and `/<todoid>/objid/<hex>`
already finds a note like any other object in the record.

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

### Web access and edits (`web`)

Two settings decide who may do what. Each is `none`, `read` or `write`:

| Setting | Governs | Default |
|---------|---------|---------|
| `--loopback` | clients whose source address is loopback: `127.0.0.0/8`, `::1`, `::ffff:127.x.x.x` | `read` |
| `--public` | every other client | `none` |

| Level | GET | `POST /update` | Edit controls |
|-------|-----|----------------|---------------|
| `none` | 403 | 403 | none |
| `read` | served | 403 | none |
| `write` | served | accepted | rendered |

The class is the TCP peer address of each request, never the `Host` header.
Both settings `none` leaves nothing to serve, so the command exits nonzero
before binding a socket. The default bind host is `localhost` when public is
`none` and `::` otherwise; an explicit `--host` (or config `host`) wins, and a
non-loopback host under `public=none` still refuses non-loopback clients. Start
prints one line, `todo web: <url>  loopback=<level>  public=<level>`.

Every option (`loopback`, `public`, `host`, `port`) defaults from the `web`
object of the todo dir's `config.json`; the command line beats config, config
beats the built-in default:

```json
{"web": {"loopback": "write", "public": "read", "host": "::", "port": 8765}}
```

An unknown key, a level outside the three, a non-string `host` or a `port`
outside 0-65535 refuses to start with a message naming it. The positional
selector and `--dump-html` are per invocation and have no config key.

At `write` the todo page is an editor for the fields the CLI can **update**,
and nothing more: the web reads and updates, it never creates or deletes.

| Control | Where | CLI command it runs |
|---------|-------|---------------------|
| Edit | Summary, Body, Long summary, AC, ActualSummary (shown even when empty) | `set --summary` / `--body` / `--long-summary` / `--ac` / `--actual-summary` |
| Edit | each note tile | `note-replace <objid>` |
| Edit | each not-done work item | `work-item-replace <objid>` |
| Up / Down | each not-done work item; the first open item has no Up, the last item no Down | `work-item-reorder <objid> <index>` |

Nothing else has a control: not State or the closing dispositions (`done`,
`checkpoint`, `blocked`, `obsolete`), not Tag, relto or Parent, not Id, Branch,
Scope or the timestamps, and no add or remove of any note, work item, tag,
relation or todo. The done prefix has no controls at all.

Edit opens an editor in the fold with Save and Cancel. Nothing is saved on
input; Save is the only write, and a successful save reloads the page. A move
saves on its click.

Every edit is `POST /update` with a JSON body:

```json
{"id": "<64-hex todo Id>", "op": "set-body", "target": "", "value": "<new text>"}
```

| `op` | `target` | `value` |
|------|----------|---------|
| `set-summary`, `set-body`, `set-long-summary`, `set-ac`, `set-actual-summary` | `""` | the field's new text |
| `note-replace` | `objid:<hex>` | the note's new raw text |
| `work-item-replace` | `objid:<hex>` | the item's new summary |
| `work-item-reorder` | `objid:<hex>` | the destination index |

The server runs the matching CLI command in-process, so its validation and
refusals are the CLI's own. Saves are last-write-wins: a save applies whatever
the page sent, even when the todo changed since the page loaded.

| Status | Means | Body |
|--------|-------|------|
| 200 | saved | `{}` |
| 400 | the command refused, or the request is malformed | `{"error": <the command's own error text>}` |
| 403 | refused before any command ran | `{"error"}` |
| 503 | the store lock is held elsewhere (the CLI's ERETRY); retry | `{"error"}` |

A 403 is any of: the client's class is not `write`; for a loopback client, the
`Host` header is not `localhost`, `127.0.0.1` or `[::1]` on the server's port
(DNS rebinding; a public client's `Host` only has to be present); `Origin` is
missing or is not `http://<that Host>` (a cross-site page); the `Content-Type`
is not `application/json`, or the body is not JSON. The JSON content type is
what forces any cross-origin request through a CORS preflight, which the server
never answers. GET requests carry no such checks beyond the class level.

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
objid integrity, relto mention sync, PR disposition for root todos, unlock of
stale locks, schema sweep.

**relto mention sync.** Every run, doctor reconciles each relto-bearing node's
derived `mention` entries against that node's own editable prose --
`Body.raw`, a note's `raw`, a WorkItem's `summary`, never a work item's
git-copied `message` -- adding one for a target the prose gained and dropping
one for a target it lost; every entry of another type is left untouched.
Idempotent to the byte: an unchanged record allocates no objid, changes no
byte, and bumps no `update_dt` on a second consecutive run. A dangling LOCAL
target is a hard finding; an unresolvable CROSS-TODO target is a soft warning
only, since the store is per-repo and a target naming a todo in another
repo's store is legitimately unresolvable here.

## Code layout: core library and front ends

Planned split of `todo.py`. Three kinds of module:

- **Core library** -- everything a front end needs that is not argument parsing
  or output formatting. The existing modules `todo_store`, `todo_db`,
  `todo_objid`, `todo_ref`, `todo_url`, `todo_search`, `todo_embed`,
  `todo_embed_apple` and `git_command` are core already. The core code still
  inside `todo.py` moves to one new module, `todo_core.py`. Core has no
  `argparse`, writes nothing to stdout and never calls `sys.exit`; it raises
  `TodoError` and the front end prints it. Core may write a diagnostic to
  stderr; three sites do (`git_fetch_if_remote`, `resolve_ticket_by_id`'s
  other-repo notice, `search_tickets`' backfill progress) and they stay as they
  are, so no command's output changes.
- **`todo.py`** -- the CLI the skill calls: argparse, every `*Command` class,
  output formatting, invocation logging, startup warnings, autocommit/autopush.
  It imports the names it uses explicitly (`from todo_core import (...)`), so
  command bodies keep calling them unqualified.
- **`todoweb.py`** -- the viewer and permalink server, an executable with the
  options `todo.py web` takes. `todo_web.py` moves into it (`git mv`), together
  with the web glue from `todo.py` (`web_config`, `WEB_DEFAULT_*`, the
  settings/bind-host logic of `WebCommand`, and the write side). It reads
  through core in-process. `todo.py web` stays as a subcommand whose body runs
  `todoweb.py` with the same argv as a child process and returns its exit code,
  so `main`'s invocation logging still records it.

Neither front end imports the other. `todo_core` imports only the core modules
above.

Dependency notes that shape the move:

- `merge_subtodo` calls `_summary_snippet`, so that helper is core although its
  other callers are in `log`.
- `todo_web.py` keeps its own `run_git`, `normalize_todo`, `current_state_name`
  and `read_todo_at_ref`. They differ from the core functions of the same names
  (`TodoWebError` instead of `TodoError`, debug tracing, a string `State`
  accepted), so swapping them for core would change the viewer.
- A test that patches a moved function patches it on `todo_core`: `todo.py`
  holds its own binding of each imported name, so patching `todo.<name>` misses
  every call made from inside core. Today's patch targets on `todo` are
  `repo_root`, `write_todo_worktree`, `run_gh` and `_run_editor`; the last stays
  in `todo.py`.

### Classification of `todo.py`

Every top-level function and class, in file order, with its line in `todo.py`
at the time of the split. `core` moves to `todo_core.py`, `todo` stays in
`todo.py`, `todoweb` moves to `todoweb.py`.

- core: `parse_state_filter` 116, `default_state_filter` 149, `resolve_state_filter` 156,
  `TodoError` 172
- todo: `EditNotInteractive` 176, `_stdio_is_interactive` 180,
  `strip_leading_html_comments` 188, `_run_editor` 206, `edit_text_via_editor` 211
- core: `repo_root` 247, `utc_now` 256, `run_git` 261, `git_fetch_if_remote` 270,
  `list_branch_refs` 282, `branch_exists` 301, `normalize_todo_schema` 307, `migrate_store`
  332, `use_store` 361, `repo_key` 380, `read_todo_at_ref` 399, `read_todo_worktree` 418,
  `_split_phrases` 461, `_nphrase_windows` 470, `_is_flat_vector` 485, `_is_vector` 494,
  `_raw_of` 504, `_tag_field_path` 516, `_embed_targets` 521, `_raw_map` 549, `_container_at`
  556, `_changed_raw_fields` 580, `_strip_vectors_at` 598, `_json_embeddings_present` 606,
  `_merge_stored_embeddings` 629, `_cheap_embedding_rows` 650, `_drop_stale_automatic_tags`
  687, `write_todo_worktree` 717, `commit_todo` 785, `head_sha` 800, `sha_matches` 808,
  `current_branch` 819, `is_all_selector` 826, `id_matches` 835, `branch_name_hint` 844,
  `candidate_refs` 850, `kebab_branch_name` 859, `current_state_name` 868, `_as_flag` 890,
  `set_state` 895, `linked_worktrees_by_branch` 963, `worktree_path_for_branch` 985,
  `intended_worktree_path` 992, `resolve_ticket_branch` 997, `promote_groom_todo` 1005,
  `maybe_init_todo_branch` 1035, `ensure_todo_worktree` 1060,
  `assert_todo_worktree_removable` 1092, `remove_todo_worktree_for_branch` 1110,
  `teardown_worktree_for_terminal_state` 1126, `apply_set_fields` 1136, `_tag_elements` 1194,
  `apply_tag_add` 1200, `apply_tag_remove` 1222, `apply_tag_clear` 1249, `tag_findings` 1273,
  `_load_corpus` 1302, `_mine_tag_candidates` 1334, `compute_auto_tags` 1355
- todo: `add_state_set_arguments` 1383
- core: `git_url_for_repo` 1424, `build_ticket_skeleton` 1432, `workitem_kind` 1562,
  `workitem_is_done` 1570, `cursor_index` 1577, `cursor_summary` 1586, `is_done` 1595,
  `_index_by_objid` 1639, `_workitem_index_by_objid` 1676, `_index_by_number` 1681,
  `_workitem_index_by_number` 1704, `resolve_workitem_index` 1709, `resolve_note_index` 1739,
  `resolve_relto_host` 1764, `require_open_workitem` 1804, `next_action` 1821, `last_sha`
  1858, `code_workitem` 1872, `start_subtodo_workitem` 1884, `merge_subtodo_workitem` 1894,
  `mark_cursor_done` 1905, `close_workitem` 1936, `closed_workitem_payload` 1978,
  `find_todos_by_id` 1994, `resolve_ticket_by_id` 2033, `mint_id` 2055, `import_json_ticket`
  2064, `import_all_json_refs` 2085, `read_todo_at_ref_legacy` 2097, `SearchTimeFilters`
  2124, `_normalize_search_date` 2142, `_parse_search_timestamp` 2149, `parse_search_query`
  2170, `_ticket_matches_time_filters` 2213, `SearchTicketsResult` 2235,
  `_ticket_matches_tag_filter` 2242, `_partition_search_candidates` 2255,
  `_text_search_match_ids` 2284, `_rrf_fuse` 2321, `resolve_embedder_names` 2331,
  `resolve_stopwords` 2367, `_solo_term_id_prefix_hit` 2397, `search_tickets` 2415
- todo: `_prompt_notes` 2632, `_prompt_section` 2680, `build_prompt_chain` 2702
- core: `load_json_file` 2743, `parse_jsonpath` 2754, `format_jsonpath` 2774,
  `available_path_options` 2781, `no_such_path_error` 2790, `resolve_path_segment` 2798,
  `get_at_path` 2819
- todo: `print_json_value` 2829
- core: `set_at_path` 2841, `subtodo_entry_from_child` 2887, `info_backlink_entry` 2897,
  `upsert_info_backlink` 2913, `remove_info_backlink` 2941, `resolve_parent_refs` 2964,
  `apply_parent_links` 2985, `reestablish_backlinks` 3037, `child_is_tracked_subtodo` 3079,
  `upsert_subtodo` 3120, `update_subtodo_state` 3133, `apply_ticket_path` 3147,
  `merge_subtodo` 3177, `wait_for_state` 3250, `commit_exists` 3307, `workitem_findings`
  3312, `unmerged_subtodos` 3394, `notes_findings` 3419, `relto_findings` 3454,
  `_prose_targets` 3513, `sync_mentions` 3526, `objid_findings` 3576, `doctor_findings` 3617,
  `doctor_warnings` 3694, `wait_graph_findings` 3764, `wait_targets_for_todo` 3804,
  `wait_cycle_findings` 3823
- todo: `TodoSubCommand` 3852, `CommandGroup` 3928, `ManagementCommand` 3938,
  `StoreMaintenanceCommand` 3944, `CorpusQueryCommand` 3948, `EnvironmentCommand` 3952,
  `TodoCrudCommand` 3956, `TodoCreateCommand` 3962, `TodoFieldCommand` 3966, `TagCommand`
  3970, `WorkItemCommand` 3974, `WorkItemEditCommand` 3980, `WorkItemProgressCommand` 3984,
  `NoteCommand` 3988, `SubtodoCommand` 3994, `SubtodoMergeCommand` 4000, `SubtodoWaitCommand`
  4004, `_command_leaves` 4018, `MintCommand` 4029, `_ordered_subdict` 4066,
  `order_ticket_fields` 4076, `elide_embedding_vectors` 4096, `ReadCommand` 4116,
  `GetJsonPathCommand` 4156, `ResolveUrlCommand` 4178, `GetCommand` 4230, `InitCommand` 4276,
  `EnsureWorktreeCommand` 4425, `AddSubtodoCommand` 4483, `SetCommand` 4586,
  `resolve_edit_target` 4706, `EditCommand` 4740, `RmCommand` 4804, `TagAddCommand` 4842,
  `TagRmCommand` 4870, `TagClearCommand` 4899, `ClearSearchDataCommand` 4975,
  `WorkItemAddCommand` 5061, `WorkItemDoneCommand` 5091, `WorkItemReadCommand` 5207
- core: `_build_relto_element` 5257
- todo: `_parse_relto_arg` 5284, `NoteAddCommand` 5305, `NoteReadCommand` 5358,
  `NoteReplaceCommand` 5390, `NoteDeleteCommand` 5431, `_relto_read_all` 5473,
  `RelToAddCommand` 5501, `RelToRemoveCommand` 5554, `RelToReadCommand` 5605,
  `WorkItemInsertCommand` 5638, `WorkItemReplaceCommand` 5685, `WorkItemDeleteCommand` 5728,
  `WorkItemReorderCommand` 5767, `WorkItemCheckpointCommand` 5859, `WorkItemBlockedCommand`
  5930, `WorkItemObsoleteCommand` 5991, `IsDoneCommand` 6051, `LastShaCommand` 6075,
  `SetJsonPathCommand` 6100, `MergeSubtodoCommand` 6161, `WaitForCommand` 6192,
  `WaitAndMergeCommand` 6223
- core: `_recompute_auto_tags` 6263, `gh_reset_gate` 6339, `gh_gate_reason` 6344,
  `gh_repo_slug` 6349, `run_gh` 6365, `_gh_classify` 6381, `_gh_json` 6406, `recorded_pr`
  6428, `gh_pr_for_todo` 6443, `reconcile_pr_state` 6474, `_doctor_one` 6533
- todo: `DoctorCommand` 6598
- core: `_summary_snippet` 6701
- todo: `_short_dt` 6707, `_ticket_oneline` 6712, `_entry_as_ticket` 6724,
  `_load_child_ticket` 6734, `_ticket_commits` 6749, `render_ticket_graph` 6785
- core: `discover_all_tickets` 6820, `forest_roots` 6846
- todo: `LogCommand` 6854
- todoweb: `web_config` 6927, `WebOp` 6962, `_web_set_op` 6968, `_cli_error_text` 6998,
  `_ThreadStream` 7005, `_thread_stream` 7042, `WebUpdater` 7052, `WebCommand` 7110
- todo: `ImportJsonCommand` 7301, `_ColumnAction` 7335, `_add_column_args` 7348
- core: `_column_value` 7374, `todo_row` 7393
- todo: `_format_rows` 7414
- core: `run_search` 7435
- todo: `SearchCommand` 7462, `EmbeddersCommand` 7561, `PromptCommand` 7585, `LsCommand`
  7618, `BaseDirCommand` 7673, `RepoDirCommand` 7698, `ExportToFileCommand` 7724,
  `MigrateToLatestCommand` 7800, `grouped_command_listing` 7835, `build_parser` 7882,
  `_redacted_env_value` 7952, `_parent_comm` 7963, `detect_caller` 7979, `_invocation_logger`
  8022, `log_invocation` 8050, `_detect_agent_framework` 8078, `_buried_claude_skills` 8102,
  `_warn_if_skills_buried` 8146, `_warn_if_store_behind` 8205, `command_class_selected` 8228,
  `_ticket_ids_in_paths` 8245, `_autocommit_message` 8266, `_git_with_index` 8273,
  `_commit_store_paths` 8282, `_autopush` 8337, `sync_file_store_git` 8345, `main` 8376

Module-level constants follow their users. Core: `JsonDict`, `LEGACY_JSON_ENV`,
`FETCH_ENABLED`, `VALID_STATES`, `STOPWORDS`, `STATE_MACROS`,
`DEFAULT_STATE_FILTER`, the `SEARCH_*` keys, `DEFAULT_STOPWORD_MIN_IDF`,
`ALLOWED_TOP_LEVEL_FIELDS`, `REQUIRED_TOP_LEVEL_FIELDS`, the `WORKITEM_*`
kinds, `SUBTODO_STATE_INFO`, `TERMINAL_PARENT_STATES`,
`WORKTREE_TEARDOWN_STATES`, and the private tables and caches the core
functions read (`_STATE_METADATA`, `_REPO_KEY_CACHE`, `_GH_GATE`, ...). `todo`:
`AUTOCOMMIT_KEY`, `AUTOPUSH_KEY`, `COMMAND_CLASSES`, `COMMAND_GROUPS`, the
`LOG_*` settings, the `*_HELP` strings, `TOP_LEVEL_EPILOG` and the read/get
field tables. `todoweb`: `WEB_CONFIG_KEY`, `WEB_DEFAULT_*`, `WEB_OPS`,
`_STREAM_INSTALL_LOCK`.

### Classification of `todo_web.py`

All of it is `todoweb`:

`_debug_enabled` 60, `_debug` 65, `TodoWebError` 75, `run_git` 79, `normalize_todo` 100,
`current_state_name` 109, `read_todo_at_ref` 119, `github_repo_url` 134, `repo_origin` 150,
`load_child_ticket` 158, `commit_message` 176, `diff_unified` 184, `_raw_field` 197,
`_summary_text` 205, `_body_text` 209, `_state_text` 213, `_state_meta` 217,
`_workitems_view` 227, `_notes_view` 268, `_subtodos_view` 291, `_objids_within` 315,
`_first_objid` 330, `_objid_badge` 338, `_holds` 351, `_section_attrs` 364, `_clamped` 388,
`_local_relto_objid` 405, `_relto_view` 422, `_relto_chips_html` 467, `_box_attrs` 499,
`_tile_controls` 518, `_wi_box` 524, `_note_box` 583, `_st_box` 606, `_parents_view` 629,
`_parent_box` 659, `_parents_html` 684, `_size_hint` 718, `_section` 723, `_edit_registry`
786, `_move_key` 835, `_move_button` 839, `_note_edit_key` 850, `_item_edit_key` 854,
`_edit_button` 858, `_md_field_html` 865, `_meta_html` 900, `_state_section_html` 947,
`_sections_html` 995, `_static_repr_html` 1126, `_page_data` 1140, `_embed_json` 1218,
`render_todo_page` 1731, `render_search_page` 1820, `_focusable_objids` 1851,
`resolve_focus` 1874, `default_bind_host` 1904, `is_loopback_client` 1909, `UpdateRefused`
1925, `Updater` 1933, `request_refusal` 1943, `handle_update` 1968, `_DualStackServer`
2003, `serve` 2020

### Test-suite layout

Test files stay flat in this directory; `run-tests.py` gains `--suite core`,
`--suite todo` and `--suite todoweb` alongside `--surface`, and with no
`--suite` runs all three. Each suite runs alone and passes alone.

- **core**: `test_todo_db.py`, `test_todo_migrate.py`, `test_todo_objid.py`,
  `test_todo_ref.py`, `test_todo_url.py`, `test_todo_embed.py`,
  `test_todo_embed_apple.py`, `test_git_command.py`, `test_todo_tiering.py`,
  plus a new `test_todo_core.py` holding the classes of `test_todo.py` and
  `test_todo_tag_impl.py` that call core functions directly instead of running
  the CLI.
- **todo**: `test_todo.py` (the CLI classes), `test_todo_all_sentinel.py`,
  `test_todo_search.py`, `test_todo_search_idf.py`, `test_todo_tag.py`,
  `test_todo_tag_impl.py` (its CLI classes).
- **todoweb**: `test_todo_web_render.py`, `test_todo_web_permalink.py`,
  `test_todo_web_bind.py`, `test_todo_web_write.py`, `WebViewerTests` from
  `test_todo.py`, and the new end-to-end test that starts `todoweb.py` on a
  free port and fetches a todo page and a permalink.

`TodoCase` (runs `todo.py` as a child process) and `TodoIntegrationCase` (runs
`todo.main` in-process) are CLI harnesses and stay with the todo suite.

### Open: the write path

`WebUpdater` applies a web edit by calling `todo.main(argv)` in-process, with
`WEB_OPS` mapping each op to CLI argv and `_ThreadStream` capturing the saving
thread's stdout/stderr. A standalone `todoweb.py` that does not import `todo.py`
cannot do that. Its tests depend on it too: `WebUpdaterCase` and
`AutocommitScopeTest` build on `TodoIntegrationCase`, `ThreadLocalCaptureTest`
patches `todo.main`, and `WebOpArgvTest` parses `WEB_OPS` with
`todo.build_parser()`. Options:

- (a) `todoweb.py` runs `todo.py <argv>` as a child process per save. Refusal
  text, the exit-75 retry status and autocommit stay the CLI's own. `_ThreadStream`
  and `ThreadLocalCaptureTest` go away; the updater tests seed and read the
  store through `todo.py` as a binary.
- (b) The four update commands (`set` text fields, `note-replace`,
  `work-item-replace`, `work-item-reorder`) move their logic into core
  functions that both `todo.py` and `todoweb.py` call. Autocommit is keyed on
  CLI command class names today, so it would need a core-level trigger, and
  `WEB_OPS` stops being argv.

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

# Recovering lost commit linkage on a finished todo

status: living document

This is a repair runbook. It takes a todo that is `done` (or otherwise
finished) but whose `WorkItems` carry **no commit shas** -- and no reliable
`BaseSha` -- and reconstructs the git linkage from what git still knows: the
branch name, the branch's commit trail, the bookkeeping commit messages
`todo.py` leaves behind, and the ticket timestamps.

The bar it aims for, weakest-to-strongest:

1. **Minimum (always achievable when the branch exists):** the todo tracks its
   `BaseSha` (the branch's initial commit) and a last `code` WorkItem carrying
   the branch tip. `todo.py last-sha` then equals `git rev-parse <branch>`
   (invariant #6), and `todo.py doctor` stops warning about a missing/foreign
   `BaseSha`.
2. **Best-effort:** each real work commit on the branch is attached, in order,
   to a `code` WorkItem, and every `merge_subtodo` item carries its merge
   marker sha.

Read [`SKILL.md`](SKILL.md) first. This runbook assumes its vocabulary
(`Branch`, `BaseSha`, the WorkItem kinds `task`/`code`/`merge_subtodo`/
`start_subtodo`, the cursor, and invariants #1/#3/#5/#6/#7).

## Why linkage gets lost

`todo.py` records shas as a side effect of the command that did the work:

- `init` captures `head_sha` right after `git checkout -b` -- before the init
  commit -- into `BaseSha` (invariant #5). So `BaseSha` is the **fork point**,
  and the init commit's parent equals it.
- `work-item-done` records the branch `HEAD` on a `code` item; it adds **no**
  bookkeeping commit, so that sha stays the branch tip (invariant #6).
- `merge-subtodo` writes a `chore(todo): subtodo <id8> merged` marker commit on
  the parent, then records that marker's sha on a `merge_subtodo` item.
- `add-subtodo` records a `start_subtodo` item with **no sha** (correct: firing
  a child is not a branch commit).

If a run was driven by hand or by "poorly worded instructions" -- code committed
directly, `WorkItems` written as done `task`s or `code` items with the `sha`
omitted, a legacy `TODO.json` imported, or work done on `dev`/`master` instead of
a dedicated branch -- those shas never got captured. Doctor then reports hard
findings ("`code` item is missing a sha", invariant #1) and/or a soft
`BaseSha ... not found` warning. This runbook fills them back in.

## Signals git still has

| Signal | How to read it | Recovers |
|--------|----------------|----------|
| Ticket `Branch` / `Scope.branch` | `todo.py get-json-path <sel> Branch` | which ref to diff |
| Branch-name convention `Id[0:8]-kebab-summary` | `git branch -a --list "<id8>-*"` | the branch when `Branch` is blank/wrong |
| Init commit `chore(todo): init ticket <id8>` (or `init subtodo <id8>`) | `git rev-list --all --grep=...` | `BaseSha` = init-commit parent |
| Branch commit trail | `git log --reverse <BaseSha>..<branch>` | ordered candidate shas for `code` items |
| Bookkeeping vs work commits | `chore(todo):` prefix marks bookkeeping; everything else is real work | which commits map to `code` items |
| Merge markers `chore(todo): subtodo <id8> merged` | `git log --grep=...` on the parent | `merge_subtodo` item shas |
| `create_dt` / `update_dt` | `todo.py get-json-path <sel> create_dt` | time-window bound (the dev/master fallback) |
| `Parent.0.Branch`, `Subtodos[].Branch` | `todo.py read <sel>` | the diff base for a subtodo; child merge points |
| Other checkouts | `git worktree list` | where the branch actually lives |

`todo.py log -v <sel>` already renders a branch's trail as `git log
<base>..<branch>` (base = `Parent.0.Branch` for a subtodo, else the first of
`dev`/`main`/`master`). Recovery is the same idea, but it writes the shas it
finds back into the record instead of only displaying them.

## Safety preconditions

- **This is the sanctioned exception to "done items are immutable history."**
  Recovery repairs the done prefix on purpose. Everywhere else, leave done items
  alone.
- **Route every write through `todo.py`** (`set-json-path`, `set --state`). Do not
  hand-edit `TODO.json`, sqlite, or git objects. Reads that must inspect real
  commits use raw `git` (that is what this runbook does); the ticket itself is
  still only touched via the CLI.
- **Snapshot before writing.** Save the current record so a bad reconstruction is
  revertible:
  ```bash
  TODO=skills/projectmanagement/todos/todo.py
  "$TODO" read <sel> > /tmp/todo-before-recover.json
  ```
- **Never invent a sha.** If a commit for a WorkItem cannot be found, leave that
  item without one and record the uncertainty (see "When you cannot map it").
  A guessed sha is worse than an honest gap.
- Do the work in the checkout where the branch lives (`cd` there; `git worktree
  list` if unsure). `todo.py` has no `--repo` flag.

## Procedure

Throughout, `<sel>` is the todo selector (a 4+ hex `Id` prefix, or `self` when
that branch is checked out) and shas are full 40-hex (`--format=%H`).

```bash
TODO=skills/projectmanagement/todos/todo.py
ID=$("$TODO" get-json-path <sel> Id | tr -d '"')
ID8=${ID:0:8}
BR=$("$TODO" get-json-path <sel> Branch | tr -d '"')
```

### Step 1 -- locate the branch

```bash
git rev-parse --verify "refs/heads/$BR"        # the happy path
```

If `Branch` is blank, wrong, or the ref is gone, fall back in order:

```bash
git branch -a --list "${ID8}-*"                # naming convention Id[0:8]-...
git log --all --oneline --grep="init ticket ${ID8}"   # the init commit
git log --all --oneline --grep="init subtodo ${ID8}"  # ... if it is a subtodo
git reflog --all | grep -i "$ID8"              # last resort: reflog
git worktree list                              # is it checked out elsewhere?
```

Once found and it disagrees with the record, fix `Branch` and `Scope.branch`
first (`printf '%s' "\"$BR\"" | "$TODO" set-json-path <sel> Branch`) so the rest
of the tooling resolves it. If **no** branch or init commit survives anywhere,
skip to "The dev/master (no dedicated branch) case."

### Step 2 -- recover BaseSha (the initial commit)

Preferred: `BaseSha` is the init commit's parent.

```bash
INIT=$(git rev-list --all --max-count=1 --grep="init ticket ${ID8}")
# for a subtodo, grep "init subtodo ${ID8}" instead
BASE=$(git rev-parse "${INIT}^")
```

Fallback when the init commit is gone (rebased/squashed): the fork point.

```bash
# base = parent branch for a subtodo, else first of dev/main/master
PBASE=$("$TODO" get-json-path <sel> Parent.0.Branch 2>/dev/null | tr -d '"')
if [ -z "$PBASE" ] || [ "$PBASE" = null ]; then
  for b in dev main master; do
    git show-ref -q --verify "refs/heads/$b" && PBASE=$b && break
  done
fi
BASE=$(git merge-base "$BR" "$PBASE")
```

Record it (only if it resolves in this repo -- else doctor will warn):

```bash
git cat-file -e "${BASE}^{commit}" && printf '%s' "\"$BASE\"" | "$TODO" set-json-path <sel> BaseSha
```

### Step 3 -- enumerate the branch trail

With `BaseSha` known, the exact commits made on this branch are
`BASE..BR`, oldest first. Separate real work from `todo.py` bookkeeping:

```bash
# every commit on the branch, oldest-first
git log --reverse --format='%H %s' "${BASE}..${BR}"

# real WORK commits only (drop chore(todo): bookkeeping)
git log --reverse --format='%H %s' --invert-grep --grep='^chore(todo):' "${BASE}..${BR}"
```

The work-commit list is the ordered candidate set for `code` WorkItems. The
`chore(todo):` commits are anchors, not work -- do not attach them as `code`
items (the one exception is the merge marker, Step 6).

### Step 4 -- the minimum bar: first and last commit

Even with zero further mapping, guarantee the two endpoints the user wants
tracked:

- **First:** `BaseSha` from Step 2 -- done.
- **Last:** the branch tip must be the sha of the last `code`/`merge` WorkItem
  (invariant #6).

```bash
TIP=$(git rev-parse "$BR")
"$TODO" last-sha <sel>        # compare; should end up equal to $TIP
```

If nothing else is recoverable, replace `WorkItems` with a single reconstructed
`code` item carrying `$TIP` (Step 7 shows the write). That satisfies invariants
#1/#3/#6/#7 and makes `last-sha == git rev-parse <branch>`.

### Step 5 -- best-effort: map work commits to code items

Order is the strongest signal, since done items form a monotonic prefix
(invariant #3) and the trail is chronological.

1. Let `W` = the ordered done `code`/`task` WorkItems that lack a sha; let `C` =
   the ordered work commits from Step 3.
2. **Counts match (`len(W) == len(C)`):** zip them positionally -- commit `i`
   backs item `i`. Highest-confidence case; take it.
3. **Counts differ:** map by content, not blindly. Match each item's `summary`
   against commit subjects (`%s`) -- conventional-commit scope/type and shared
   keywords usually line up. A single item often spans several commits: attach
   the **last** commit of its span (its sha), so the prefix stays monotonic and
   the final item still lands on `$TIP`. Leave genuinely unmatched items without
   a sha rather than forcing a pairing.
4. Preserve the frozen fields (`kind`, `done`, `summary`, `subtodo_id`); only
   add/fix `sha`. Never reorder the done prefix.

Timestamps disambiguate ties: a commit's date should fall between the ticket's
`create_dt` and `update_dt`; drop candidates outside that window.

### Step 6 -- recover subtodo linkage

- **`start_subtodo` items:** keep them sha-less (invariant #1 exempts them).
  Confirm the child still exists: `todo.py read <child-id8>`; if the child
  branch is gone, that becomes a doctor soft warning, not an error.
- **`merge_subtodo` items:** the recorded sha is the parent-side marker commit.
  Recover it per child:
  ```bash
  git rev-list --all --max-count=1 --grep="subtodo ${CHILD8} merged"
  ```
  Attach that sha to the child's `merge_subtodo` item. Cross-check that the
  child branch tip is actually reachable from the parent
  (`git merge-base --is-ancestor <child-tip> <BR>`); if not, the merge was never
  landed -- surface it rather than fabricating the marker.

### Step 7 -- write back and validate

Reconstruct the whole `WorkItems` array as JSON in the scratchpad, then set it in
one call (the sanctioned way to replace `WorkItems`), and re-validate:

```bash
# author the repaired array (example: one recovered code item at the tip)
cat > /tmp/workitems.json <<'JSON'
[
  {"kind": "code", "summary": "<carried-over summary>", "sha": "<TIP-or-mapped-sha>", "done": true}
]
JSON
"$TODO" set-json-path <sel> WorkItems --file /tmp/workitems.json

"$TODO" doctor <sel>                 # must be ok (findings empty); warnings tolerated
"$TODO" last-sha <sel>               # must equal: git rev-parse <branch>
"$TODO" log -v <sel>                 # trail should render against the branch
```

Doctor is the acceptance gate. Resolve every hard **finding** (missing sha on a
`code`/`merge` item = #1; a done item out of the prefix = #3; the last item is a
`start_subtodo` = #6; a not-done item on a `done` todo = #7). Soft **warnings**
(a sha or `subtodo_id` unresolvable in this checkout) are acceptable for
transitional or cross-repo todos -- note them, do not force them away.

## When you cannot map it

Record the gap honestly instead of guessing:

- Leave the item sha-less and append a short note to the ticket `Body`
  (`todo.py set --body=...`) naming what could not be linked and why (branch
  gone, squashed history, work done on `dev`).
- If the whole branch is unrecoverable but a commit window is known, capture the
  window (first/last sha of the window) as `BaseSha` and a single `code` item,
  and say so in the body.
- A todo that cannot reach the minimum bar (no branch, no init commit, no
  window) should be left as-is with a body note; do not manufacture linkage to
  satisfy doctor.

## The dev/master (no dedicated branch) case

Sloppy runs land on `dev`/`master` with no ticket branch to diff. There is no
`BASE..BR` window, so bound the work by identity and time instead:

1. Anchor on the init commit if one exists:
   `git log --oneline --grep="init ticket ${ID8}"`. Its parent is still a usable
   `BaseSha`.
2. Otherwise bound by timestamp on the mainline:
   ```bash
   C=$("$TODO" get-json-path <sel> create_dt | tr -d '"')
   U=$("$TODO" get-json-path <sel> update_dt | tr -d '"')
   git log --reverse --format='%H %s' --since="$C" --until="$U" master
   ```
   Filter that window to commits whose subjects match the ticket
   `Summary`/`Body`/`AC`; the first is the effective base, the last is the
   effective tip.
3. Record `BaseSha` = first-in-window's parent, and map the matched commits to
   `code` items per Step 5. Add a `Body` note that this todo was worked on a
   shared branch and the linkage is time-window-inferred, not exact.

## Publishing the recovered branches

Once linkage is repaired, the branches are the durable asset (see SKILL.md
"Worktree placement"): push them so another machine on the **same core repo** can
check them out and follow the detailed frequentcommit trail (`todo.py log -v`,
`git log <BaseSha>..<branch>`).

The branches associated with a todo are its own `Branch` plus every
`Subtodos[].Branch`. For a flat parent, one filter is enough:

```bash
TODO=skills/projectmanagement/todos/todo.py

# sanctioned: todo.py owns the read; system jq filters stdout
"$TODO" read <id> | jq '[.Branch] + [.Subtodos[]?.Branch] | map(select(. != null and . != "")) | unique'
```

**Caveat -- `Subtodos` is one level deep.** `read <id>` embeds only a summary row
per *direct* child (`Id`, `Branch`, `Summary`, `State`), not the recursive
subtree. Subtodos-of-subtodos live in their own tickets. For the full transitive
closure, walk the child `Id`s (`.Subtodos[]?.Id`) breadth-first, reading each:

```bash
#!/usr/bin/env bash
# All branch names under a root todo (this ticket + every nested subtodo).
todo_branches() {
  local todo=skills/projectmanagement/todos/todo.py
  local queue="$1" seen=" " out=""
  while [ -n "$queue" ]; do
    local id=${queue%%$'\n'*}
    if [ "$id" = "$queue" ]; then queue=""; else queue=${queue#*$'\n'}; fi
    [ -z "$id" ] && continue
    case "$seen" in *" $id "*) continue ;; esac      # dedupe visited ids
    seen="$seen$id "
    local j; j=$("$todo" read "$id" 2>/dev/null) || continue
    out="$out$(printf '%s' "$j" | jq -r '([.Branch] + [.Subtodos[]?.Branch])[] | select(. // "" != "")')"$'\n'
    queue="$queue"$'\n'"$(printf '%s' "$j" | jq -r '.Subtodos[]?.Id')"
  done
  printf '%s' "$out" | sed '/^$/d' | sort -u
}

todo_branches <root-id>          # bash (not zsh); prints one branch per line
```

Push only the branches that actually exist locally -- a merged/absorbed child may
have no surviving ref, and pushing a missing branch errors:

```bash
todo_branches <root-id> | while read -r b; do
  git show-ref -q --verify "refs/heads/$b" && git push origin "$b"
done
```

The receiving machine then `git fetch`es, and `todo.py read`/`log -v` there
resolve the same shas -- since `BaseSha`, the `code` item shas, and the branches
now all point at commits the shared remote carries. Branches whose refs are gone
locally cannot be published; note them (they will show as doctor soft warnings on
the other machine, not hard failures).

## Future automation (not built)

This runbook is manual on purpose -- linkage recovery is rare and judgement-heavy
(fuzzy commit-to-item matching, the shared-branch case). If it becomes routine, a
`todo.py recover <sel>` could mechanize the unambiguous parts: fill `BaseSha`
from the init commit's parent, and, when the work-commit count equals the
sha-less `code`-item count, zip them positionally -- then leave the ambiguous
cases for a human. Do not implement it before repeated real use shows the exact
shape needed.

## Related

- [`SKILL.md`](SKILL.md) -- the linkage model, invariants, and the normal
  lifecycle this runbook repairs back into.
- `frequentcommits` -- the policy that makes each WorkItem map to a small,
  trackable commit in the first place; recovery is only necessary when that
  policy was not followed.

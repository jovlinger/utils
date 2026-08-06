# RECIPE: Retrofit a todo from an already-merged/pushed PR (RetrofitFromPR)

Build a todo record for work that already happened on a real git branch/PR without
ever being tracked through `todo.py`, so the record's `WorkItems`, `Branch`, and
`BaseSha` are the ACTUAL git history -- not narrated as a reconstruction, and not
worked forward from here. This is memory capture for a project already finished.

# When to use

- A PR merged (or was pushed and is under review) whose work was never run through
  the normal `mint` -> `init` -> `work-item-done` loop.
- You want that PR's story discoverable later the same way a live todo's is: by
  `todo.py read`, linked under a parent epic, with a WorkItems trail a diff-viewer
  can resolve per-commit.

Do NOT use this to plan or track new work -- that's the normal lifecycle (`todos`
SKILL.md). This recipe only back-fills history for work that is already done.

# Non-negotiable: the record must not read as a reconstruction

The todo's `Summary`/`Body`/`WorkItems` text should look exactly like what a real
forward run would have produced. Do not write "retrospective", "backfilled",
"reconstructed", or similar into any user-visible field. (This recipe file, and any
`[CI: ...]` provenance markers inside a WorkItem's own `message` documenting a
rollup decision, are the only places that kind of language belongs -- see below.)

# Shape

1. **Identify the real git facts** -- do not invent them:
   ```bash
   gh pr view <N> --json headRefOid,baseRefOid,body,title
   git merge-base --is-ancestor <candidate-base-sha> <head-sha> && echo ok
   git log --reverse --format='%H|%s' <base-sha>..<head-sha>
   ```
   Prefer the branch's actual creation point (the `origin/<default>` tip *when the
   branch was cut*, if you know it from session history) over `gh`'s `baseRefOid`,
   which reports the CURRENT merge-base and drifts under squash-merge rewrites of
   the base branch.

2. **CI is push-granular, not commit-granular.** A commit that was never itself a
   push tip has no independent CI verdict -- it inherits whatever the next push's
   result was. Query the actual pipeline per push (`sem get pipeline <id>`, or
   whatever this repo's CI is) rather than guessing from commit position.

3. **Rollup policy for a red push, before the next green one:** Only auto-roll a
   failing push's commit forward into the next successful push's WorkItem when the
   ONLY failing block(s) were **cosmetic** (lint / format / black-check-mode style;
   anything that fixes itself with no behavior change). A red **functional/test**
   block always gets its own WorkItem, no matter what follows it -- never silently
   absorbed. Concretely: don't trust the label alone; pull the pipeline's per-block
   results and check nothing outside the cosmetic block(s) shows `failed` (a
   downstream `stopped` from short-circuiting is not itself a failure).

   When eligible, the merged item's `sha` = the SUCCESSFUL push's commit (never the
   red one); `message` = an explicit `[CI: push at <red-sha> failed <block> --
   cosmetic-only; rolled forward into this commit per policy]` marker, followed by
   BOTH original commit messages in full, separated by `---`. Nothing is deleted,
   only compressed forward -- the red sha is still named in the text even though it
   no longer has its own list entry.

4. **Tail failure -- the branch HEAD's own push never went green.** Still give it
   its own `code` WorkItem (there's nothing later to roll it into); mark it
   honestly with a `[CI: red at push time]`-style note in `message` rather than
   presenting it as clean. Never drop the final state or pretend it passed.

5. **Build the WorkItems array directly**, one item per surviving sha, in branch
   order -- `kind: "code"`, `done: true`, real `sha`, `summary` = that commit's own
   subject line (do not paraphrase; the commit already has a description),
   `message` = that commit's full body (plus any rollup marker from step 3/4):
   ```bash
   python3 -c '
   import json, subprocess
   def msg(sha): return subprocess.check_output(["git","log","-1","--format=%B",sha], text=True).strip()
   items = [{"kind":"code","done":True,"sha":s,"summary":msg(s).splitlines()[0],"message":msg(s)}
            for s in [...shas in order...]]
   print(json.dumps(items))
   ' > /tmp/workitems.json
   todo.py set-json-path <id> WorkItems --file /tmp/workitems.json
   ```

6. **Set `BaseSha` directly** (normally an `init`-only field; there is no real
   `init` here since this todo's own `Branch` never got created by the tool):
   ```bash
   printf '%s' '"<start-sha>"' | todo.py set-json-path <id> BaseSha
   ```

7. **Point `Branch` / `Scope.branch` at the REAL branch**, not `mint`'s generated
   placeholder label -- so anything that resolves a todo's git history by branch
   name (a diff viewer, `git log <branch>`) finds the actual commits matching the
   WorkItems' shas:
   ```bash
   printf '%s' '"<real-branch-name>"' | todo.py set-json-path <id> Branch
   printf '%s' '"<real-branch-name>"' | todo.py set-json-path <id> Scope.branch
   ```

8. **State**: `merged {pr: N}` is correct and honest if the work actually went to a
   PR -- that transition means "handed off via a pushed PR" per the `todos` SKILL,
   regardless of when the todo record itself was written.

9. **Parent linkage**: hang it off the relevant epic via `set <id> --parent <id>`
   (an INFO back-link), not `add-subtodo` -- `add-subtodo` requires creating the
   child's branch fresh from the parent's tip, which doesn't fit an already-existing
   independent branch.

10. **Sanity-check before calling it done**: confirm the chain resolves in THIS
    repo, not just in the PR metadata:
    ```bash
    git cat-file -t <base-sha> && git cat-file -t <head-sha>
    git merge-base --is-ancestor <base-sha> <head-sha> && echo ok
    git diff --stat <base-sha> <head-sha>   # should show the expected changeset
    todo.py doctor <id>                      # must report ok: true
    ```

# Known sharp edge: `doctor`'s PR reconciliation skips parent-linked todos

`doctor`'s automatic PR-disposition reconciliation (filling in `merge_commit` once
a PR merges, or flipping to `rejected` if closed unmerged) only runs for **root**
todos -- any todo with a `Parent` ref is treated as a subtodo, where `merged` means
"absorbed by parent," not "handed off to a PR." Step 9's parent link therefore
means the `pr: N` you set in step 8 will **not self-update**. If you want live
reconciliation, either don't parent-link it, or accept updating `merge_commit` by
hand later (`todo.py set <id> --state merged --merge-commit <sha>`).

# Related

- `todos` SKILL.md -- the normal forward lifecycle this recipe deliberately bypasses.
- `RECIPE:diagnose-unknown-failures.md` -- another recipe-shaped variant of the same
  mechanism, for fan-out rather than backfill.

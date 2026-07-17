# RECIPE: Diagnose unknown failures (DiagnoseAndSpawn)
Fan a batch of failures with unknown / mixed root causes out into one subtodo per
distinct underlying issue, fix them in parallel, then merge them back.

# When to use

- You have a pile of failures (a red test run, a batch of tickets, a broken build)
  whose root causes are unknown or heterogeneous.
- You do not yet know how many *distinct* problems are in the pile -- it might be 1
  shared cause or 8 independent ones.
- The fixes are independent enough to run in parallel on separate branches.

Do NOT use for a single known cause, or for a short linear fix -- that is a plain
WorkItem, not a fan-out.

# Shape

- `Body.raw` = the WHOLE raw problem, verbatim (the full failure dump / list). This
  is the durable record a zero-context subagent reads via `todo.py prompt`.
- Seed `WorkItems` = exactly one: **DiagnoseAndSpawn**.

Working DiagnoseAndSpawn (it is the cursor):

1. **Scan** the failures and cluster them into N *distinct underlying issues*
   (shared root cause, not just shared test-name prefix). Reading tracebacks /
   source beats grouping by name.
2. For each issue, append a task WorkItem "Fix: <short issue desc>"
   (`todo.py work-item-add --summary=...`).
3. Append a final **barrier** WorkItem "Wait-and-merge issue subtodos"
   (`todo.py work-item-add --summary=...`).
4. Complete DiagnoseAndSpawn itself: `todo.py work-item-done -m "diagnosed N
   issues; queued per-issue subtodos + barrier"` (clean tree -> records HEAD).

Then the normal todo loop runs itself out:

5. Each "Fix: ..." task is now the cursor -> `todo.py add-subtodo --summary=...`
   (this CONVERTS the cursor task into a `start_subtodo` and creates the child
   branch). Immediately launch a subagent to work that child on its branch. Repeat
   per issue -- the children run in parallel.
6. When the cursor reaches the barrier: for each child, **`git merge <child-branch>`
   into the parent FIRST**, THEN `todo.py merge-subtodo <id>` (or `wait-and-merge
   <ids>`) to record the bookkeeping. `wait-and-merge`/`merge-subtodo` do **todo
   bookkeeping only -- they do NOT git-merge the child's code** (the recorded
   `merge_subtodo` sha is a bookkeeping commit, not a real merge). If you skip the
   `git merge`, the fixes never reach the parent branch even though the graph shows
   `merged`. Order the merges to avoid conflicts on any shared file.
7. Record the real code-landing (`work-item-add` + `work-item-done` so the last
   work item's sha == branch HEAD, invariant #6), then `todo.py set --state done
   --actual-summary=...`.

# Mechanics notes (validated against todo.py)

- `add-subtodo` calls `mark_cursor_done(parent, start_subtodo_workitem(...))` -- it
  COMPLETES the current cursor item as a `start_subtodo`. So DiagnoseAndSpawn cannot
  "hold" the spawns inside itself; it only PLANS (append one task per issue + the
  barrier) and completes. The spawn happens as each issue task is worked -- one
  cursor task per child. Parallelism is preserved: `add-subtodo` just creates the
  branch; you launch a subagent per child right after.
- "Push a new work-item to run next" is already `todo.py work-item-insert` (inserts
  at the cursor). Use it when one issue turns out to be several -- split it in place.
  No new todo.py ability is required for this recipe.
- The barrier can be a plain task the agent recognizes and runs `wait-and-merge` on.
  Optionally attach `execution: {primitive: "wait-and-merge", wait_for: [ids]}` via
  `todo.py set-json-path <id> WorkItems.<n>.execution` so `work-item-read`'s `next`
  hint auto-suggests `wait-and-merge`.
- Every subtodo must terminate (done -> merged, or surface via userneeded/stopped);
  the parent only goes `done` after all tracked subtodos are `merged`
  (`doctor` enforces this).
- **Cross-subtodo communication (note-to-parent):** a subtodo that COMPLETES but has
  a soft concern (impedance, a shared-file warning, "I lacked context about the
  user's motivations", a design call it made anyway) does NOT halt with
  `userneeded`. It finishes and appends the concern to its `set --state done
  --actual-summary` as a trailing `# note-to-parent: ...` section; `merge-subtodo`
  reuses ActualSummary as the merge message, so the note surfaces to the parent
  there. Reserve `userneeded`/`stopped` for HARD blocks only. (Codify a dedicated
  field later if the appendix convention proves out.)
- **Do NOT resume a torn-down child to run `self` commands.** Once a subtodo's
  worktree is removed (teardown), a resumed child agent has no checkout of its own
  branch; running any `todo.py <cmd> self` from there defaults to the PARENT
  worktree and mutates the PARENT todo (observed: it flipped the parent to `done`
  and overwrote its ActualSummary). Set a child's final ActualSummary in its single
  run BEFORE teardown; amend it only from a fresh checkout of the CHILD branch.

# Command cheat-sheet

```bash
cd <repo>                      # todo.py takes repo from $(gitroot); no --repo flag
todo.py init --summary="Diagnose <batch>" --body="<whole raw failure dump>" --ac="..."
todo.py work-item-add --summary="DiagnoseAndSpawn: cluster failures, spawn a subtodo per issue, wait-and-merge"
todo.py set --state working
# --- work DiagnoseAndSpawn ---
todo.py work-item-add --summary="Fix: <issue 1>"      # one per distinct issue
todo.py work-item-add --summary="Fix: <issue N>"
todo.py work-item-add --summary="Wait-and-merge issue subtodos"   # barrier
todo.py work-item-done -m "diagnosed N issues; queued subtodos + barrier"
# --- spawn loop (cursor is now Fix: issue 1) ---
todo.py add-subtodo --summary="Fix: <issue 1>"        # -> child branch; launch a subagent on it
...                                                    # repeat to issue N
todo.py wait-and-merge <child-id-1> ... <child-id-N>  # barrier: poll to done, merge each
todo.py set --state done --actual-summary="..."
```

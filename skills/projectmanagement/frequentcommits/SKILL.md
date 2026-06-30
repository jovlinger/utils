---
name: frequentcommits
description: >-
  Test-first, chunked, frequent-commit implementation workflow (sizing and
  sequencing policy; todos is the storage mechanism). TRIGGER, necessary and
  sufficient: the user says "frequentcommit(s)", "frequent commits", "chunk",
  or asks for incremental / test-first delivery -- invoke immediately on any of
  these. The full policy and chunking rules live in this skill body and load
  only when triggered.
disable-model-invocation: false
---

# Frequent Commits

status: living document

Incremental delivery for any **non-trivial** PLAN or instruction set: split
work into trivial steps, lock completion with an **end test** up front, then
walk the list one chunk at a time -- unit test, fix, mark done, commit.

Prefer the **`todos`** skill for chunk tracking; if TODO is unavailable, a
sequential list in **`PLAN.md`** (or equivalent plan doc) is enough.

**Mechanism vs policy.** `todo.py` / `TODO.json` (and `PLAN.md`) are
*mechanism*: they store the chunk list and the commands that mutate it. This
skill is *policy*: how to split, size, sequence, refine, and when to commit.
Keep them apart -- do not push sizing or sequencing rules into the tool, and do
not depend here on any storage layout beyond "an ordered chunk list exists,
head = next work."

**Refinement realism (progressive elaboration).** You cannot fully specify
distant work, so do not pretend to. Near the head, chunks are small, detailed,
and ready to implement now; far from the head they stay larger and fuzzier,
sharpened only as they approach. Plan in focus, not in full -- a precise tail is
wasted effort that the near work will invalidate.

## Related skills

| When | Use |
|------|-----|
| Branch-bound ticket + `TODO.json` | `todos` |
| GOAL / PLAN / IMPL lifecycle docs | `project-lifecycle` |
| Pause mid-chunk with partial state | `bookmark-management` |

Chunk-list storage (a `TODO.json` field + a `todo.py` command) is **mechanism
owned by `todos`**; sizing and sequencing are **policy owned here** -- see
[Chunk list on TODO](#chunk-list-on-todo).

---

## 1. Split into manageable chunks

Break the work before coding.

| Tracker | Chunk size | Notes |
|---------|------------|-------|
| `TODO.json` (+ `todos`) | Can be **larger**; keep as sequential chunks, escalating only **major units** to sub-branches (see the split decision below) |
| `PLAN.md` list | Must stay **small** -- each item should be trivial on its own |

**Non-uniform sizing (both trackers):**

- **Proximate** (at or near the head): small, detailed, ready to implement now.
- **Far future**: larger, fuzzier -- refine when the item nears the head.

Some chunks **cannot** be subdivided at the current level. Those are **major
features**: give them a **sub-branch** and a **dependent TODO** (see `todos`),
not more bullets at this level.

### Sub-branch vs sequential chunk (the split decision)

Default to **sequential chunks** in one tracker on one branch: a single coherent
line of changes, one actor, orderable head-first. Most work is this.

Escalate a chunk to a **sub-branch + dependent TODO** only when it is a *major
unit* -- any of:

- it cannot be reduced to trivial steps at this level (it needs its own plan);
- it can run **in parallel** with sibling units (different actor / branch);
- it wants its own END test and review boundary.

Dependent TODOs form a flexible **sequential + parallel network that joins back
at the parent** when its children reach `done`. That network is **mechanism
owned by `todos`** (its `waiting` / `waited` graph, plus a future doctor that
asserts well-formedness / acyclicity) and is **currently Deferred**. Until it
ships, prefer sequential chunks; treat any sub-branch split as a manual
convention and keep the join explicit in the parent `Body`.

Rule of thumb: if you would cut a git branch for it anyway (isolation, parallel
actor, independent review), make it a sub-branch + dependent TODO; otherwise it
is a sequential chunk.

### Record the tracker choice

State the choice and its reason in the planning unit itself -- `TODO.json`
`Body` (or the head of `PLAN.md`): which tracker, why (single feature vs
network), and whether sub-branches are expected. One sentence, so the next actor
inherits the decision instead of re-litigating it.

---

## 2. Keep a trivial step at the head

Maintain an ordered list of small tasks inside the planning unit:

- **PLAN.md:** markdown checklist; trivial item at the top.
- **TODO.json:** same idea in a mutable top-level field (name TBD; see below).

Sub-todos in `TODO.json` are optional; a flat chunk list at the top level is
enough for v1.

### Chunk list on TODO

Split by layer, not by negotiation:

- **Mechanism (`todos` / `todo.py` owns):** a top-level array field (placeholder
  `Chunks`) of `{ "summary": string, "done": boolean }`, head = next work, plus
  a command to append and to mark done. The field name and command are the
  tool's to fix; do not invent conflicting names in shared repos.
- **Policy (this skill owns):** how chunks are sized and sequenced -- near =
  small and detailed, far = broad (Refinement realism) -- that only the head
  chunk is in flight, and that you mark done then commit.

Until the tool ships the command, mark a chunk done with a JSON CLI patch on the
field. For **PLAN.md**, mark done with a check (`- [x]`) on the line.

---

## 3. Write the END test first (before any chunk work)

Before touching the first chunk, write the **completion gate test**:

- Acts as **acceptance criteria** for the branch effort.
- **Literate style:** prose explains the happy path; each test step maps to the
  MVP flow for this branch.
- Prefer **end-to-end**, **black-box**, or **integration** tests over unit scope.
- Lives where the project keeps tests (not prescribed here).

Do not start chunk iteration until this test exists (may be red).

---

## 4. Work one chunk (loop start)

For the **first** item in the plan list or TODO chunk head:

1. Write a **small unit test** that demonstrates the chunk and prevents
   backsliding on that behavior.
2. Implement until the new test **passes**.
3. Run **all tests** written so far (unit + end test if fast enough; at minimum
   all unit tests from prior chunks plus the new one).
4. **Mark the chunk done** (PLAN checkbox or TODO chunk field / `todo.py`).
5. **Commit** to the branch.

### Commit message rules

- **Brief** comments focused on **WHY**, not what (the diff shows what).
- **One comment line per file touched**, each explaining why that file changed.
- Example shape:

```text
chunk: initialize sensor mock

tests/test_aht20_sleep.py: lock sleep/wake repro before driver fix
firmware/aht20.c: reset bus after deep sleep so reads are not stale
```

---

## 5. Iterate

Repeat section 4 for each subsequent chunk:

- **New unit test per chunk** (narrow scope; guards that step).
- Before commit: **all previous unit tests pass**, plus the new one.
- Mark chunk done; commit with why-per-file messages.

Keep refining far-future plan/TODO entries as they move toward the head.

---

## 6. End test passed early?

If the **END test passes** before the chunk list is exhausted:

**Stop and ask the user.** Do not auto-close the ticket or declare done.

Likely causes:

- Chunks were **over-split** (work was already sufficient).
- Acceptance criteria / END test were **under-specified** (test does not capture
  the real MVP).

Only the user decides whether to trim remaining chunks, strengthen the END
test, or stop anyway.

---

## Workflow checklist

```
- [ ] Split work (TODO preferred, else PLAN.md); major indivisibles -> sub-branch + TODO
- [ ] Non-uniform list: detailed head, fuzzy tail
- [ ] Write END (E2E/integration) test -- literate, MVP-mapped
- [ ] For each chunk at head:
      unit test -> implement -> all prior unit tests green -> mark done -> commit (why/file)
- [ ] If END test green early -> ask user
```

---

## Open questions

1. **Chunk field name** on `TODO.json` and `todo.py` subcommand -- negotiate with
   `todos` (placeholder: `Chunks`).
2. **END test location/naming** -- project-specific; no cross-repo convention yet.
3. **Run END test every chunk?** -- run all unit tests every time; END test on
   a schedule vs every commit left to project cost (default: run when cheap;
   mandatory before declaring branch done).

## Assumptions

- **A1:** "Trivial" means one commit-sized change with one focused unit test.
- **A2:** PLAN.md fallback uses the same END-test-first and iterate rules.
- **A3:** Frequent commits are on the **current feature branch**, not main, unless
  the user directs otherwise.
- **A4:** Chunk list order is strict; only the head chunk is in flight at once
  unless the user explicitly parallelizes.

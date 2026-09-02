# Cursor agents: read this when working todos

status: living document - **Cursor-only addendum** (normative for Cursor)

Normative detail still lives in [`GROOMING.md`](GROOMING.md) and [`WORKING.md`](WORKING.md).
This file restates the rules Cursor agents keep breaking, in plain language.

---

## 0. When this applies

You are in Cursor. The user said work / proceed / continue on a todo, or you
picked up a ticket in `working` state. **Read this file before you touch code.**

### Paths (do not forget)

| Path | What it is |
|------|------------|
| `utils/skills/` | Canonical skills tree (git) |
| `~/.claude/skills/` | Symlink to `utils/skills` |
| `~/.cursor/skills/` | Symlink to `utils/skills` |

Same inode. **One tree.** Never "sync both copies."

`todo.py`: `utils/skills/projectmanagement/todos/todo.py`

---

## 1. Do not stop until you must

**"Work the todo" means keep going.** Not "do one or two items and write a status
report."

### Keep working when

- `todo.py work-item-read` shows another item at the cursor.
- `todo.py is-done` exits non-zero.
- The current item finished and nothing blocks the next one.
- The user said proceed / continue / work (they did not say stop).

### Stop only when

- `todo.py is-done` is true and you are in the finish sequence
  ([`WORKING.md` section 6](WORKING.md#6-finish-and-remove-the-worktree)).
- You hit `userneeded` / `stopped` and recorded why
  ([`WORKING.md` section 5](WORKING.md#5-handle-userneeded-or-stopped)).
- The same concrete step failed twice (P1: ask the smallest unblocker).
- The user interrupted you (Ctrl-C, deny, or explicit stop).

### Banned stopping reasons

- "Good place to report progress."
- "Next item looks like a different kind of work."
- "I did two commits already."
- Ending with **Next:** as if you are handing off to a future session.

If you need to surface status, do it **while continuing**, not instead of
continuing.

---

## 2. Use the agent tier on the WorkItem tag

Every WorkItem summary starts with `[HICAP]`, `[MIDCAP]`, or `[LOCAP]`.
**That tag is an order, not decoration.**

Read the tag on the **current cursor item** from `todo.py work-item-read`.
Match it to a model **before** you implement.

### Tier -> Cursor model (2026-08 map)

| Tag | Use for | Cursor models |
|-----|---------|---------------|
| `[HICAP]` | Architecture, hazard-dense first implementations, END tests, ambiguous debugging | Claude Fable 5; Claude Opus 5 (+ 4.x); GPT-5.6 Sol; GPT-5.5 high effort; Grok 4.6 high effort |
| `[MIDCAP]` | Pattern-following code, inventories, tests, checklists | Claude Sonnet 5 (+ 4.x); Composer 2.5; Grok 4.5/4.6 daily; GPT-5.6 Terra; Gemini 3 Pro |
| `[LOCAP]` | Run-and-report, formatting, trivial mechanical edits | Claude 4.5 Haiku; Composer 2.5 Fast; GPT-5.6 Luna; Gemini Flash family |

Refresh against [`GROOMING.md#capability-tiers`](GROOMING.md#capability-tiers) when
the picker changes. `Auto` is a router, not a tier.

### How to comply in Cursor

1. **Orchestrator (you)** polls `work-item-read`, commits bookkeeping, merges
   subtodos, runs `doctor`, sets `done`. Bookkeeping can stay on your current model.
2. **Item work** must run at the tagged tier:
   - If your current model matches the tag: implement directly.
   - If it does not: spawn a **Task** subagent with the matching `model` slug from
     the Task tool list, or tell the user you need a model switch before coding.
3. **Never** run a `[HICAP]` item on Composer/MIDCAP because it is convenient.
4. **Never** spawn HICAP to guess product decisions listed as unresolved on the
   ticket; ask the user ([`GROOMING.md` rule 3](GROOMING.md#capability-tiers)).

### HICAP is bounded

HICAP lands **one exemplar** (pattern + guard tests), then MIDCAP rolls out
copies. Example: `[HICAP]` writes the END test contract; `[MIDCAP]` wires the
rest of the pipeline to it.

---

## 3. Drive the loop (do not freestyle)

When working a ticket, run this loop until `is-done` or a real stop condition:

```bash
TODO=skills/projectmanagement/todos/todo.py   # or absolute path to todo.py

"$TODO" prompt <id>
"$TODO" work-item-read <id>                   # read the [TIER] tag here
# dispatch item at that tier (section 2)
# code in the todo worktree only (WORKING.md worktree setup)
"$TODO" work-item-done <id>                   # from todo branch checkout
"$TODO" work-item-read <id>                   # immediately poll again
```

Rules:

- **Worktree:** code edits only in the linked worktree for the todo branch.
  Main checkout stays on `DEFAULT_BRANCH`.
- **Sequential:** one WorkItem at a time unless the user or grooming authorizes
  parallel fan-out.
- **`init` before `working`:** if State is still `groom`, run
  `todo.py init --id <id> --stay-on-parent` first.
- **CLI-only:** never read/write the store JSON by hand.

---

## 4. Self-check before you end a turn

Answer honestly. If any answer is wrong, **do not end the turn** -- keep working
or escalate with `userneeded`.

| Question | Required answer |
|----------|-----------------|
| Did the user ask me to work the todo? | Then I should still be in the loop unless a real stop condition fired. |
| Is `is-done` false? | Then I am not finished. |
| Did I run the cursor item at its `[TIER]`? | Must be yes for any code I wrote this turn. |
| Did I stop after a progress report? | That is a failure mode; continue. |

---

## 5. Where to look next

| Need | Open |
|------|------|
| Tier rules, model map, grooming | [`GROOMING.md`](GROOMING.md) |
| Worktree, finish, subtodos, blocked | [`WORKING.md`](WORKING.md) |
| CLI flags, schema | [`IMPLEMENTATION.md`](IMPLEMENTATION.md) |

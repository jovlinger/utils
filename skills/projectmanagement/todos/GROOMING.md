# Grooming todos

status: living document · **normative owner** for ticket design, decomposition,
capability targeting, and make-vs-work policy

Operating an already-ready ticket → [`WORKING.md`](WORKING.md)  
Command / schema details → [`IMPLEMENTATION.md`](IMPLEMENTATION.md)  
Intent router → [`SKILL.md`](SKILL.md)

---

## Two-phase: make vs work

| Phase | User signal | Commands | Git |
|-------|-------------|----------|-----|
| **Make** | “make a todo”, plan, groom | `mint` then `set <id> …` | none — store-only `groom` record |
| **Work** | “work the todo”, design ready | `init --id <id>` (prefer `--stay-on-parent`) | creates branch, state `ready` |

```bash
TODO=skills/projectmanagement/todos/todo.py
ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."
# iterate with set while State is groom (summary refreshes Branch label)

"$TODO" init --id "$ID" --stay-on-parent   # when ready to work
```

`init --summary=...` still one-shot-creates (backward compatible). Default for
new work is mint → set → init. Exact flags:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#identity-and-listing).

States: `groom` = collecting data, branchless; `ready` = has a branch, ready to
enter the [`WORKING.md`](WORKING.md) loop.

---

## Required grooming outputs

Before `init` / before implementation agents fan out, the ticket should have:

| Output | Notes |
|--------|-------|
| `Summary.raw` | Human title |
| `Body.raw` | Description / WHY |
| `AC` | Concrete acceptance criteria |
| `Scope` | At least one of `git_url`, `path_from_root` (+ `branch` with `git_url`). Do **not** set `path_to_project` (stripped by migration) |
| Tiered WorkItems | Head of list small enough for one trackable unit (`frequentcommits`) |
| Child plan | For each planned subtodo: independence, integration order, sequential vs authorized parallel |
| Unresolved decisions | Listed for the user — do not guess product calls with a HICAP planner |

Seed WorkItems while still `groom` (store-only):

```bash
todo.py work-item-add <id> --summary="[MIDCAP] ..."
```

Wholesale replan: `set-json-path <id> WorkItems` (JSON array) — see
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#work-items). Edit the not-done frontier;
never rewrite the done prefix.

---

## Ready-to-init checklist

- [ ] Summary, Body, AC present and agreed
- [ ] Scope locators set (no `path_to_project`)
- [ ] WorkItems cover the path to AC; head items are one unit each
- [ ] Each WorkItem / planned subtodo tagged with a capability tier
- [ ] Subtodo vs WorkItem choice recorded (table below)
- [ ] Open product decisions asked of the user (or explicitly deferred in Body)
- [ ] Id captured for all later commands

Then: `todo.py init --id <id> --stay-on-parent` and follow
[`WORKING.md`](WORKING.md#1-start-or-resume).

---

## WorkItem vs subtodo

**Default when told to “work” a todo with subtodos: sequential stack order, one
context, one child at a time.** Do not fan out parallel subagents unless the
user explicitly asks, or the children are genuinely independent context-heavy
research domains (below). `execution.mode: "parallel"` means children *may* run
concurrently — not that you should.

| Use | When |
|-----|------|
| **Parent WorkItem** | Short linear edit; single subsystem; no distinct branch artifact |
| **Sequential subtodo** | Separate branch/context helps, but order or shared understanding matters — **default** |
| **Parallel subtodos** | User requested parallel **or** independent fact-finding domains that would bloat one window; each child lands a branch-bound artifact |

Prefer subtodos when:

| Signal | Why |
|--------|-----|
| Independent fact-finding domains | Unrelated files/CLIs; parent stays synthesis-only |
| Scoped research before a merge doc | Parent AC is a matrix; children produce notes/commits |
| Child artifact is branch-bound | Parent reads via git merge + `todo.py read`, not chat memory |

Do **not** file empty shell subtodos with no distinct artifact.

Tracked children: always `add-subtodo` (merge obligation). Context-only hang-off:
`set <child> --parent <id>` (INFO backlink) — no merge obligation. Details:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#subtodos-and-waiting).

Integration after children finish is owned by
[`WORKING.md`](WORKING.md#4-wait-and-integrate-child-work) (git merge first,
then bookkeeping).

---

## Capability tiers

Assign every delegated unit (subtodo or parent-local WorkItem) a tier by **task
shape**, not brand prestige. Map current vendor models into these tiers at use
time.

| Tier | Meaning | Typical work |
|------|---------|--------------|
| HICAP | Flagship reasoning; spend sparingly | Architecture, hazard-dense first implementations, ambiguous debugging |
| MIDCAP | Default workhorse | Pattern-following code, inventories, tests, skill checklists |
| LOCAP | Small/fast/cheap | Run-and-report verification, formatting, trivial mechanical edits |

Example mapping (2026, Anthropic): HICAP ≈ Opus-class, MIDCAP ≈ Sonnet-class,
LOCAP ≈ Haiku-class — illustrative only.

Rules:

1. **Default MIDCAP.** Escalate/de-escalate on shape, not importance theater.
2. **HICAP is bounded.** Land one exemplar (class/pattern/sketch + guard tests),
   then roll out on MIDCAP as separate items.
3. **Human answers are free.** Ask during grooming; do not spawn HICAP to guess
   product decisions.
4. **Parent-local ≠ parent-model.** Orchestrator keeps bookkeeping; item work may
   be a cheaper subagent.
5. **LOCAP is run-and-report** with escalation of the *fix* (not the re-run) on red.
6. **Escalate on discovered ambiguity** — stop rather than guess.
7. **Miss-cost guard** — do not drop to LOCAP where silent incompleteness is expensive
   (cross-repo checklists, populated-DB migrations, etc.).
8. **Tag it** — prefix summaries / subtodos with `[HICAP]`, `[MIDCAP]`, `[LOCAP]`
   (optional `/model`).

**Driver loop shape:** HICAP grooms and reviews; MID/LOCAP implement bounded
items; re-groom before the next authorized fan-out. Implementation never starts
from an ungroomed item. Parallel fan-out remains subordinate to the sequential
default above.

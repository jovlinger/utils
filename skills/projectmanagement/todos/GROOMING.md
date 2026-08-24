# Grooming todos

status: living document - **normative owner** for ticket design, decomposition,
capability targeting, and make-vs-work policy

Operating an already-ready ticket -> [`WORKING.md`](WORKING.md)
Command / schema details -> [`IMPLEMENTATION.md`](IMPLEMENTATION.md)
Intent router -> [`SKILL.md`](SKILL.md)

Boot-read order below: tiers (who you are) -> make vs work -> required outputs ->
decompose -> LongSummary craft -> ready-to-init checklist.

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

### Claude examples (stable reference)

Keep these as the durable mental model; remap other vendors against them:

| Tier | Claude examples |
|------|-----------------|
| HICAP | Opus-class -- Claude Opus 5, Claude Fable 5 (and recent Opus 4.x) |
| MIDCAP | Sonnet-class -- Claude Sonnet 5 (and recent Sonnet 4.x) |
| LOCAP | Haiku-class -- Claude 4.5 Haiku |

Example mapping (2026, Anthropic): HICAP ~= Opus-class, MIDCAP ~= Sonnet-class,
LOCAP ~= Haiku-class -- illustrative only.

### Cursor-available models (2026-08 map)

Illustrative, by **task shape** against the Claude anchors above. Fast / Mini /
Nano / Flash variants drop one tier unless the WorkItem is already LOCAP.
`Auto` is a router, not a tier.

| Tier | Cursor models (common picker / docs names) |
|------|--------------------------------------------|
| HICAP | Claude Fable 5; Claude Opus 5 (and Opus 4.8 / 4.7 / 4.6 / 4.5); GPT-5.6 Sol; GPT-5.5 (high effort); Grok 4.6 (high effort) |
| MIDCAP | Claude Sonnet 5 (and Sonnet 4.6 / 4.5); **Composer 2.5**; Grok 4.5; Grok 4.6 (medium / daily); GPT-5.6 Terra; GPT-5.4 / 5.3 Codex (non-mini); Gemini 3.1 Pro / 3 Pro; Kimi K3 |
| LOCAP | Claude 4.5 Haiku; Composer 2.5 Fast; Composer 2; GPT-5.6 Luna; GPT-5.4 Mini / Nano; GPT-5 Mini / Codex Mini; Gemini 3.7 / 3.6 / 3.5 / 3 / 2.5 Flash; GLM 5.2; Kimi K2.7 Code |

Refresh this table when Cursor's model lineup shifts; the Claude anchors stay.

Rules:

1. **Default MIDCAP.** Escalate/de-escalate on shape, not importance theater.
2. **HICAP is bounded.** Land one exemplar (class/pattern/sketch + guard tests),
   then roll out on MIDCAP as separate items.
3. **Human answers are free.** Ask during grooming; do not spawn HICAP to guess
   product decisions.
4. **Parent-local != parent-model.** Orchestrator keeps bookkeeping; item work may
   be a cheaper subagent.
5. **LOCAP is run-and-report** with escalation of the *fix* (not the re-run) on red.
6. **Escalate on discovered ambiguity** -- stop rather than guess.
7. **Miss-cost guard** -- do not drop to LOCAP where silent incompleteness is expensive
   (cross-repo checklists, populated-DB migrations, etc.).
8. **Tag it** -- prefix summaries / subtodos with `[HICAP]`, `[MIDCAP]`, `[LOCAP]`
   (optional `/model`).

**Driver loop shape:** HICAP grooms and reviews; MID/LOCAP implement bounded
items; re-groom before the next authorized fan-out. Implementation never starts
from an ungroomed item. Parallel fan-out remains subordinate to the sequential
default below.

---

## Two-phase: make vs work

| Phase | User signal | Commands | Git |
|-------|-------------|----------|-----|
| **Make** | "make a todo", plan, groom | `mint` then `set <id> ...` | none -- store-only `groom` record |
| **Work** | "work the todo", design ready | `init --id <id>` (prefer `--stay-on-parent`) | creates branch, state `ready` |

```bash
TODO=skills/projectmanagement/todos/todo.py
ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."
# iterate with set while State is groom (summary refreshes Branch label)

"$TODO" init --id "$ID" --stay-on-parent   # when ready to work
```

`init --summary=...` still one-shot-creates (backward compatible). Default for
new work is mint -> set -> init. Exact flags:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#identity-and-listing).

States: `groom` = collecting data, branchless; `ready` = has a branch, ready to
enter the [`WORKING.md`](WORKING.md) loop.

---

## Required grooming outputs

Before `init` / before implementation agents fan out, the ticket should have:

| Output | Notes |
|--------|-------|
| `Summary.raw` | Human title. Optimize purely for clarity -- do not reorder or pad it to game the auto-derived Branch label (below). |
| `Body.raw` | Description / WHY |
| `LongSummary.raw` | Optional. A reader-first summary of `Body`, and the text the summary embedding is computed from (below) |
| `AC` | Concrete acceptance criteria |
| `Scope` | At least one of `git_url`, `path_from_root` (+ `branch` with `git_url`). Do **not** set `path_to_project` (stripped by migration) |
| Tiered WorkItems | Head of list small enough for one trackable unit (`frequentcommits`) |
| Child plan | For each planned subtodo: independence, integration order, sequential vs authorized parallel |
| Unresolved decisions | Listed for the user -- do not guess product calls with a HICAP planner |

Branch label defaults to the first 4 non-stopword words of `Summary.raw`
(`kebab_branch_name`), which is a mechanical default, not a requirement. Weak
guidance: if that default buries the todo's most distinctive aspect (e.g. a
clear summary happens to lead with generic words), the grooming agent has
leeway to override the Branch label directly rather than reshaping the
summary -- `set-json-path <id> Branch` (and mirror in `Scope.branch`) while
still `groom`, or `init --branch <name>` at promotion time.

Seed WorkItems while still `groom` (store-only):

```bash
todo.py work-item-add <id> --summary="[MIDCAP] ..."
```

Wholesale replan: `set-json-path <id> WorkItems` (JSON array) -- see
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#work-items). Edit the not-done frontier;
never rewrite the done prefix.

---

## WorkItem vs subtodo

**Default when told to "work" a todo with subtodos: sequential stack order, one
context, one child at a time.** Do not fan out parallel subagents unless the
user explicitly asks, or the children are genuinely independent context-heavy
research domains (below). `execution.mode: "parallel"` means children *may* run
concurrently -- not that you should.

| Use | When |
|-----|------|
| **Parent WorkItem** | Short linear edit; single subsystem; no distinct branch artifact |
| **Sequential subtodo** | Separate branch/context helps, but order or shared understanding matters -- **default** |
| **Parallel subtodos** | User requested parallel **or** independent fact-finding domains that would bloat one window; each child lands a branch-bound artifact |

Prefer subtodos when:

| Signal | Why |
|--------|-----|
| Independent fact-finding domains | Unrelated files/CLIs; parent stays synthesis-only |
| Scoped research before a merge doc | Parent AC is a matrix; children produce notes/commits |
| Child artifact is branch-bound | Parent reads via git merge + `todo.py read`, not chat memory |

Do **not** file empty shell subtodos with no distinct artifact.

Tracked children: always `add-subtodo` (merge obligation). Context-only hang-off:
`set <child> --parent <id>` (INFO backlink) -- no merge obligation. Details:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#subtodos-and-waiting).

Integration after children finish is owned by
[`WORKING.md`](WORKING.md#4-wait-and-integrate-child-work) (git merge first,
then bookkeeping).

---

## Writing a LongSummary

`LongSummary` is a careful summary of the `Body`, written to inform a human
reader without overwhelming them -- and, at the same time, the text the summary
**embedding** is computed from. The field contract (its two permitted readers,
the deliberate absence of any tool coupling to `Body`, and the staleness
obligation that follows) is owned by
[`IMPLEMENTATION.md`](IMPLEMENTATION.md#longsummary-the-field-contract). Read it
before writing one.

Write for a human skimming the ticket, knowing the same text becomes a vector.
Those two goals mostly agree: both reward dense, concrete, self-contained prose
and punish padding.

| Do | Don't |
|----|-------|
| Lead with what the todo IS and why it exists | Open with "This todo..." or restate the `Summary` |
| Name the concrete nouns: files, commands, fields, systems | Use vague placeholders ("the relevant module") an embedder cannot match |
| Keep it self-contained: it is read without the `Body` | Refer to "the above", "the second option", or the `Body`'s structure |
| A few short paragraphs, prose | Deep bullet trees, tables, ASCII art -- they read badly and embed worse |
| Include the decisions and constraints that were RATIFIED | Reproduce the whole reasoning that led to them |
| Say what was deliberately excluded, if it is load-bearing | Pad to look thorough |

**Write it as if it were an important embedding**, because it is. Terms a future
searcher would plausibly type should actually appear in it -- the single most
useful rule when you are unsure what to include.

**Length** is whatever informs without overwhelming, typically a handful of
paragraphs. A `LongSummary` approaching the length of its `Body` has failed at
both jobs.

**Not the `pr-description` format.** That skill is tailored for FINISHED work
(what broke, what was fixed, how it was verified) and is deliberately terse to
the point of being a pointer for someone with the diff open. A `LongSummary`
describes a todo at ANY stage, for a reader with nothing else in front of them.
The spirit -- reader-first, no padding -- carries over; the shape does not.

```bash
todo.py set <id> --long-summary="..."   # write or replace it
todo.py get <id> --long-summary         # read it back
```

Because nothing couples the two fields, a materially rewritten `Body` obliges
you to rewrite an existing `LongSummary` in the same breath.

---

## Ready-to-init checklist

- [ ] Summary, Body, AC present and agreed
- [ ] Scope locators set (no `path_to_project`)
- [ ] WorkItems cover the path to AC; head items are one unit each
- [ ] Each WorkItem / planned subtodo tagged with a capability tier
- [ ] Subtodo vs WorkItem choice recorded (table above)
- [ ] Open product decisions asked of the user (or explicitly deferred in Body)
- [ ] Id captured for all later commands

Then: `todo.py init --id <id> --stay-on-parent` and follow
[`WORKING.md`](WORKING.md#1-start-or-resume).
